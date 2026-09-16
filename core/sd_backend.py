"""이미지 생성 백엔드 — ComfyUI 노드 그래프를 A1111 REST 와 같은 모양의 호출로 감싼다.

`sd_generator.py` 는 원래 A1111 의 `/sdapi/v1/txt2img` 에 payload 를 던지고 base64 를 받았다.
ComfyUI 에는 그런 엔드포인트가 없다 — 노드 그래프를 통째로 큐에 넣고(`/prompt`), 실행이 끝나기를
기다렸다가(`/history/{id}`), 저장된 파일을 받아온다(`/view`). 그 차이를 이 파일이 흡수해서,
호출부는 `BACKEND.txt2img(spec)` 한 줄만 알면 되게 한다.

이렇게 분리해 두는 이유는 모델 세대 때문이다. 지금은 SD1.5 를 쓰지만 SDXL 로 올리는 것은
`RenderSpec` 의 checkpoint/width/height 를 바꾸는 일이 되어야 하고, 생성 로직 7곳을 다시
헤집는 일이 되어서는 안 된다.

A1111 과 다른 점 중 호출부가 알아야 하는 것:
- **체크포인트 전역 상태가 없다.** `/sdapi/v1/options` 로 모델을 갈아끼우는 개념이 없고,
  체크포인트는 그래프 노드의 입력이다. 그래서 요청마다 독립적이고, 모델 교체 경쟁이 없다.
- **ENSD(31337) 에 대응하는 설정이 없다.** 같은 시드를 넣어도 A1111 이 그린 기존 이미지를
  그대로 재현하지 못한다. 기존 자산은 보존하고 신규 생성분부터 이 백엔드 규약을 따른다.
- ADetailer 는 `FaceDetailer`(Impact Pack), Hires 2차 패스는 `LatentUpscale` + 두 번째
  `KSampler`, Clip skip 은 `CLIPSetLastLayer`, ToMe 는 `TomePatchModel` 로 각각 대응한다.
"""
import io
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field

COMFY_URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8188").rstrip("/")
CLIENT_ID = "trpg-" + uuid.uuid4().hex[:8]
SAVE_PREFIX = "trpg"
KEEP_PNG = os.environ.get("COMFY_KEEP_PNG", "").strip() not in ("", "0", "false", "False")

# A1111 이름 -> ComfyUI 이름. 기존 코드가 A1111 표기로 샘플러를 적어 두었기 때문에 그대로 받는다.
SAMPLER_MAP = {
    "DPM++ 2M Karras": ("dpmpp_2m", "karras"),
    "DPM++ SDE Karras": ("dpmpp_sde", "karras"),
    "DPM++ 2M": ("dpmpp_2m", "normal"),
    "Euler a": ("euler_ancestral", "normal"),
    "Euler": ("euler", "normal"),
    "DDIM": ("ddim", "normal"),
}


def split_sampler(name):
    """'DPM++ 2M Karras' -> ('dpmpp_2m', 'karras'). 모르는 이름이면 기본값으로 떨어진다."""
    return SAMPLER_MAP.get((name or "").strip(), ("dpmpp_2m", "karras"))


@dataclass
class RenderSpec:
    """백엔드 중립 렌더 파라미터. A1111 payload 대신 이것을 만든다."""
    prompt: str
    negative_prompt: str = ""
    checkpoint: str = ""
    width: int = 512
    height: int = 512
    steps: int = 20
    cfg_scale: float = 7.0
    seed: int = -1
    sampler_name: str = "DPM++ 2M Karras"
    clip_skip: int = 2
    denoise: float = 1.0                  # img2img 에서만 1.0 미만
    loras: tuple = ()                     # ((파일명, 가중치), ...)
    # ADetailer 대응 — 얼굴만 전체 해상도로 다시 그린다
    adetailer: bool = False
    ad_prompt: str = ""
    ad_negative_prompt: str = ""
    ad_denoise: float = 0.4
    ad_model: str = "bbox/face_yolov8n.pt"
    ad_confidence: float = 0.3
    # Hires 2차 패스 대응 (A1111 enable_hr / hr_scale / hr_second_pass_steps / denoising_strength)
    hires_scale: float = 0.0              # 0 이면 사용하지 않음
    hires_steps: int = 9
    hires_denoise: float = 0.35
    tome_ratio: float = 0.0               # 0 이면 사용하지 않음
    kind: str = "image"                   # 저장 경로 구분용 라벨

    def meta_payload(self):
        """`_render_meta()` 가 기대하는 A1111 payload 모양 — 메타 기록 호환용."""
        return {
            "prompt": self.prompt,
            "negative_prompt": self.negative_prompt,
            "steps": self.steps,
            "sampler_name": self.sampler_name,
            "cfg_scale": self.cfg_scale,
            "width": self.width,
            "height": self.height,
            "seed": self.seed,
        }


class ComfyError(RuntimeError):
    pass


class ComfyBackend:
    def __init__(self, url=None, timeout=600):
        self.url = (url or COMFY_URL).rstrip("/")
        self.timeout = timeout

    # --- HTTP ---------------------------------------------------------------

    def _get(self, path, raw=False, timeout=30):
        with urllib.request.urlopen(self.url + path, timeout=timeout) as r:
            return r.read() if raw else json.load(r)

    def _post(self, path, payload, timeout=60):
        req = urllib.request.Request(self.url + path, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)

    def available(self):
        try:
            self._get("/system_stats", timeout=5)
            return True
        except Exception:
            return False

    def vram(self):
        """{'total_mb','free_mb','used_mb'} — A1111 `/sdapi/v1/memory` 자리를 대신한다.
        ComfyUI 는 응답 스키마가 다르다: devices[0].vram_total / vram_free (바이트)."""
        d = self._get("/system_stats", timeout=5)
        dev = (d.get("devices") or [{}])[0]
        total = dev.get("vram_total")
        free = dev.get("vram_free")
        if total is None or free is None:
            return {}
        mb = 1048576
        # used 를 따로 반올림하면 total-free 와 1MB 어긋난다. 세 값이 서로 맞는 편이 쓰기 좋다.
        total_mb, free_mb = round(total / mb), round(free / mb)
        return {"total_mb": total_mb, "free_mb": free_mb, "used_mb": total_mb - free_mb,
                "torch_used_mb": round((dev.get("torch_vram_total") or 0) / mb)}

    def upload_image(self, image, name=None):
        """PIL Image 또는 bytes 를 ComfyUI input 폴더로 올린다. LoadImage 가 이 이름을 참조한다."""
        if hasattr(image, "save"):
            buf = io.BytesIO()
            image.save(buf, "PNG")
            data = buf.getvalue()
        else:
            data = image
        name = name or ("trpg_init_%s.png" % uuid.uuid4().hex[:8])
        boundary = "----trpg" + uuid.uuid4().hex
        body = b"".join([
            ("--%s\r\nContent-Disposition: form-data; name=\"image\"; filename=\"%s\"\r\n"
             "Content-Type: image/png\r\n\r\n" % (boundary, name)).encode(),
            data,
            ("\r\n--%s\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n"
             "--%s--\r\n" % (boundary, boundary)).encode(),
        ])
        req = urllib.request.Request(self.url + "/upload/image", data=body,
                                     headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.load(r)
        return d.get("name", name), d.get("subfolder", "")

    # --- 그래프 ---------------------------------------------------------------

    def _base_nodes(self, spec):
        """체크포인트 -> (LoRA) -> clip skip -> 프롬프트 인코딩까지. 이후 노드가 참조할 핸들을 돌려준다."""
        sampler, scheduler = split_sampler(spec.sampler_name)
        g = {"1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": spec.checkpoint}}}
        model, clip, vae = ["1", 0], ["1", 1], ["1", 2]
        for i, (lora_name, weight) in enumerate(spec.loras or (), start=40):
            nid = str(i)
            g[nid] = {"class_type": "LoraLoader",
                      "inputs": {"lora_name": lora_name, "strength_model": weight,
                                 "strength_clip": weight, "model": model, "clip": clip}}
            model, clip = [nid, 0], [nid, 1]
        if spec.tome_ratio:
            g["30"] = {"class_type": "TomePatchModel",
                       "inputs": {"model": model, "ratio": spec.tome_ratio}}
            model = ["30", 0]
        if spec.clip_skip and spec.clip_skip > 1:
            # A1111 의 Clip skip 2 = 마지막에서 두 번째 레이어 = ComfyUI 의 -2
            g["31"] = {"class_type": "CLIPSetLastLayer",
                       "inputs": {"clip": clip, "stop_at_clip_layer": -abs(spec.clip_skip)}}
            clip = ["31", 0]
        g["2"] = {"class_type": "CLIPTextEncode", "inputs": {"text": spec.prompt, "clip": clip}}
        g["3"] = {"class_type": "CLIPTextEncode",
                  "inputs": {"text": spec.negative_prompt or "", "clip": clip}}
        return g, {"model": model, "clip": clip, "vae": vae, "pos": ["2", 0], "neg": ["3", 0],
                   "sampler": sampler, "scheduler": scheduler}

    def _sampler_chain(self, g, h, spec, latent):
        """KSampler (+ Hires 2차 패스) -> VAEDecode -> (FaceDetailer) -> SaveImage."""
        seed = spec.seed if spec.seed is not None and spec.seed >= 0 else int(uuid.uuid4().int % (2 ** 32))
        g["5"] = {"class_type": "KSampler",
                  "inputs": {"seed": seed, "steps": spec.steps, "cfg": spec.cfg_scale,
                             "sampler_name": h["sampler"], "scheduler": h["scheduler"],
                             "denoise": spec.denoise, "model": h["model"],
                             "positive": h["pos"], "negative": h["neg"], "latent_image": latent}}
        out_latent = ["5", 0]
        if spec.hires_scale and spec.hires_scale > 1.0:
            # A1111 Hires fix = 잠재공간을 키우고 낮은 denoise 로 한 번 더 확산한다.
            # 화질은 업스케일러가 아니라 이 2차 확산에서 나온다 (sd_generation_recipe_ref 실측).
            g["6"] = {"class_type": "LatentUpscale",
                      "inputs": {"samples": out_latent, "upscale_method": "bislerp",
                                 "width": int(spec.width * spec.hires_scale) // 8 * 8,
                                 "height": int(spec.height * spec.hires_scale) // 8 * 8,
                                 "crop": "disabled"}}
            g["7"] = {"class_type": "KSampler",
                      "inputs": {"seed": seed, "steps": spec.hires_steps, "cfg": spec.cfg_scale,
                                 "sampler_name": h["sampler"], "scheduler": h["scheduler"],
                                 "denoise": spec.hires_denoise, "model": h["model"],
                                 "positive": h["pos"], "negative": h["neg"], "latent_image": ["6", 0]}}
            out_latent = ["7", 0]
        g["8"] = {"class_type": "VAEDecode", "inputs": {"samples": out_latent, "vae": h["vae"]}}
        image = ["8", 0]
        if spec.adetailer:
            g["9"] = {"class_type": "UltralyticsDetectorProvider",
                      "inputs": {"model_name": spec.ad_model}}
            g["10"] = {"class_type": "CLIPTextEncode",
                       "inputs": {"text": "face, " + (spec.ad_prompt or spec.prompt), "clip": h["clip"]}}
            g["11"] = {"class_type": "CLIPTextEncode",
                       "inputs": {"text": spec.ad_negative_prompt or spec.negative_prompt or "",
                                  "clip": h["clip"]}}
            g["12"] = {"class_type": "FaceDetailer",
                       "inputs": {"image": image, "model": h["model"], "clip": h["clip"],
                                  "vae": h["vae"], "guide_size": 512, "guide_size_for": True,
                                  "max_size": 1024, "seed": seed, "steps": spec.steps,
                                  "cfg": spec.cfg_scale, "sampler_name": h["sampler"],
                                  "scheduler": h["scheduler"], "positive": ["10", 0],
                                  "negative": ["11", 0], "denoise": spec.ad_denoise,
                                  "feather": 5, "noise_mask": True, "force_inpaint": True,
                                  "bbox_threshold": spec.ad_confidence, "bbox_dilation": 10,
                                  "bbox_crop_factor": 3.0, "sam_detection_hint": "center-1",
                                  "sam_dilation": 0, "sam_threshold": 0.93, "sam_bbox_expansion": 0,
                                  "sam_mask_hint_threshold": 0.7,
                                  "sam_mask_hint_use_negative": "False", "drop_size": 10,
                                  "bbox_detector": ["9", 0], "wildcard": "", "cycle": 1}}
            image = ["12", 0]
        # 기본은 PreviewImage — ComfyUI 의 temp 폴더에 쓰고 우리가 즉시 받아간다. SaveImage 로 두면
        # 렌더마다 output/ 에 PNG(장당 ~1MB)가 영구히 쌓이는데, 최종 자산은 어차피 호출부가 WEBP 로
        # 따로 저장하므로 중복이다. 원본 PNG 를 보관하고 싶으면 COMFY_KEEP_PNG=1.
        if KEEP_PNG:
            g["20"] = {"class_type": "SaveImage",
                       "inputs": {"images": image,
                                  "filename_prefix": "%s/%s" % (SAVE_PREFIX, spec.kind)}}
        else:
            g["20"] = {"class_type": "PreviewImage", "inputs": {"images": image}}
        return g, seed

    def build_txt2img(self, spec):
        g, h = self._base_nodes(spec)
        g["4"] = {"class_type": "EmptyLatentImage",
                  "inputs": {"width": spec.width, "height": spec.height, "batch_size": 1}}
        return self._sampler_chain(g, h, spec, ["4", 0])

    def build_img2img(self, spec, image_name):
        g, h = self._base_nodes(spec)
        g["4"] = {"class_type": "LoadImage", "inputs": {"image": image_name}}
        g["41"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["4", 0], "vae": h["vae"]}}
        return self._sampler_chain(g, h, spec, ["41", 0])

    # --- 실행 ---------------------------------------------------------------

    def run(self, graph, timeout=None):
        """큐에 넣고 끝날 때까지 기다린 뒤 이미지 바이트 목록을 돌려준다."""
        timeout = timeout or self.timeout
        try:
            pid = self._post("/prompt", {"prompt": graph, "client_id": CLIENT_ID})["prompt_id"]
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:500]
            raise ComfyError("ComfyUI 가 그래프를 거부했다 (HTTP %s): %s" % (e.code, detail))
        t0 = time.time()
        while True:
            if time.time() - t0 > timeout:
                raise ComfyError("렌더 %d초 초과 (prompt_id=%s)" % (timeout, pid))
            time.sleep(0.5)
            hist = self._get("/history/%s" % pid, timeout=30)
            entry = hist.get(pid)
            if not entry:
                continue
            status = entry.get("status", {})
            if status.get("status_str") == "error":
                raise ComfyError("ComfyUI 실행 오류: %s" % json.dumps(status)[:500])
            files = [img for node in entry.get("outputs", {}).values()
                     for img in node.get("images", [])]
            if files:
                return [self.fetch(f) for f in files]

    def fetch(self, img):
        q = urllib.parse.urlencode({"filename": img["filename"],
                                    "subfolder": img.get("subfolder", ""),
                                    "type": img.get("type", "output")})
        return self._get("/view?" + q, raw=True, timeout=120)

    # --- 호출부가 쓰는 두 개 -------------------------------------------------

    def txt2img(self, spec, timeout=None):
        graph, seed = self.build_txt2img(spec)
        images = self.run(graph, timeout)
        return {"images": images, "seed": seed, "graph": graph}

    def img2img(self, spec, init_image, timeout=None):
        name, _ = self.upload_image(init_image)
        graph, seed = self.build_img2img(spec, name)
        images = self.run(graph, timeout)
        return {"images": images, "seed": seed, "graph": graph}


BACKEND = ComfyBackend()
