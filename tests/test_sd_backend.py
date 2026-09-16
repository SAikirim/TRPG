"""sd_backend 그래프 구성 검증 + ComfyUI 스모크 렌더.

그래프는 JSON 이라 조용히 틀린다 — 노드는 만들어졌는데 아무도 참조하지 않거나(그래서 무시되거나),
엉뚱한 노드를 참조해도 예외가 나지 않는다. 그래서 "노드가 있다"가 아니라 **연결이 실제로 이어졌는지**
를 본다. 실렌더 테스트는 ComfyUI 가 떠 있을 때만 돈다.

실행: python -m unittest discover -s tests -v      (프로젝트 루트에서)
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.sd_backend import ComfyBackend, RenderSpec, split_sampler  # noqa: E402

BACKEND = ComfyBackend()
LIVE = BACKEND.available()
PERSON_CKPT = os.environ.get("SD_PERSON_CKPT", "neverendingDreamNED_v122BakedVae.safetensors")


def types_of(graph):
    return {nid: n["class_type"] for nid, n in graph.items()}


def find(graph, class_type):
    return [nid for nid, n in graph.items() if n["class_type"] == class_type]


def inputs_of(graph, class_type):
    return graph[find(graph, class_type)[0]]["inputs"]


class SamplerMapping(unittest.TestCase):
    def test_a1111_names_split(self):
        self.assertEqual(split_sampler("DPM++ 2M Karras"), ("dpmpp_2m", "karras"))
        self.assertEqual(split_sampler("Euler a"), ("euler_ancestral", "normal"))

    def test_unknown_name_falls_back(self):
        # 모르는 이름에 예외를 내면 생성 전체가 죽는다. 기본값으로 떨어지는 편이 낫다.
        self.assertEqual(split_sampler("전혀 없는 샘플러"), ("dpmpp_2m", "karras"))


class Txt2ImgGraph(unittest.TestCase):
    def setUp(self):
        self.spec = RenderSpec(prompt="a girl", negative_prompt="lowres",
                               checkpoint=PERSON_CKPT, width=728, height=1104,
                               steps=20, cfg_scale=7, seed=1234, kind="sprite")

    def test_minimal_chain_is_connected(self):
        g, seed = BACKEND.build_txt2img(self.spec)
        self.assertEqual(seed, 1234)
        ks = inputs_of(g, "KSampler")
        self.assertEqual(ks["latent_image"], ["4", 0])          # EmptyLatentImage
        self.assertEqual(ks["steps"], 20)
        self.assertEqual(ks["denoise"], 1.0)
        latent = inputs_of(g, "EmptyLatentImage")
        self.assertEqual((latent["width"], latent["height"]), (728, 1104))
        out_node = g["20"]                                      # PreviewImage 또는 SaveImage
        self.assertEqual(out_node["inputs"]["images"], ["8", 0])  # VAEDecode 출력
        self.assertIn(out_node["class_type"], ("PreviewImage", "SaveImage"))

    def test_clip_skip_is_wired_into_prompts(self):
        g, _ = BACKEND.build_txt2img(self.spec)
        skip = find(g, "CLIPSetLastLayer")
        self.assertEqual(len(skip), 1)
        self.assertEqual(g[skip[0]]["inputs"]["stop_at_clip_layer"], -2)
        # 인코더 두 개가 모두 clip skip 을 거친 clip 을 봐야 한다 (한쪽만 거치면 조용히 어긋난다)
        for nid in find(g, "CLIPTextEncode"):
            self.assertEqual(g[nid]["inputs"]["clip"], [skip[0], 0])

    def test_seed_negative_gets_randomized(self):
        spec = RenderSpec(prompt="x", checkpoint=PERSON_CKPT, seed=-1)
        _, seed = BACKEND.build_txt2img(spec)
        self.assertGreaterEqual(seed, 0)

    def test_lora_chain_order(self):
        spec = RenderSpec(prompt="x", checkpoint=PERSON_CKPT,
                          loras=(("a.safetensors", 0.4), ("b.safetensors", 0.6)))
        g, _ = BACKEND.build_txt2img(spec)
        loras = sorted(find(g, "LoraLoader"))
        self.assertEqual(len(loras), 2)
        # 두 번째 LoRA 는 첫 번째의 출력을 받아야 한다 — 체크포인트를 직접 받으면 첫 LoRA 가 무시된다
        self.assertEqual(g[loras[1]]["inputs"]["model"], [loras[0], 0])   # LoraLoader 출력 0 = MODEL
        self.assertEqual(g[loras[1]]["inputs"]["clip"], [loras[0], 1])    # 출력 1 = CLIP
        self.assertEqual(g[loras[0]]["inputs"]["model"], ["1", 0])

    def test_hires_second_pass(self):
        spec = RenderSpec(prompt="x", checkpoint=PERSON_CKPT, width=512, height=768,
                          hires_scale=1.4, hires_steps=9, hires_denoise=0.35)
        g, _ = BACKEND.build_txt2img(spec)
        up = inputs_of(g, "LatentUpscale")
        self.assertEqual((up["width"], up["height"]), (712, 1072))   # 8의 배수로 내림
        second = g["7"]["inputs"]
        self.assertEqual(second["latent_image"], ["6", 0])
        self.assertEqual(second["denoise"], 0.35)
        self.assertEqual(second["steps"], 9)
        self.assertEqual(inputs_of(g, "VAEDecode")["samples"], ["7", 0])

    def test_no_hires_when_scale_unset(self):
        g, _ = BACKEND.build_txt2img(self.spec)
        self.assertEqual(find(g, "LatentUpscale"), [])
        self.assertEqual(inputs_of(g, "VAEDecode")["samples"], ["5", 0])

    def test_adetailer_replaces_saved_image(self):
        spec = RenderSpec(prompt="a girl", negative_prompt="lowres", checkpoint=PERSON_CKPT,
                          adetailer=True, ad_prompt="a girl", ad_denoise=0.4)
        g, _ = BACKEND.build_txt2img(spec)
        fd = find(g, "FaceDetailer")
        self.assertEqual(len(fd), 1)
        fdi = g[fd[0]]["inputs"]
        self.assertEqual(fdi["image"], ["8", 0])                   # VAEDecode 결과를 받아서
        self.assertEqual(g["20"]["inputs"]["images"], [fd[0], 0])   # 출력은 FaceDetailer 결과로
        self.assertEqual(fdi["denoise"], 0.4)
        self.assertEqual(g[fdi["bbox_detector"][0]]["class_type"], "UltralyticsDetectorProvider")
        self.assertTrue(g[fdi["positive"][0]]["inputs"]["text"].startswith("face, "))

    def test_tome_patches_model_before_sampler(self):
        spec = RenderSpec(prompt="x", checkpoint=PERSON_CKPT, tome_ratio=0.45)
        g, _ = BACKEND.build_txt2img(spec)
        tome = find(g, "TomePatchModel")
        self.assertEqual(len(tome), 1)
        self.assertEqual(inputs_of(g, "KSampler")["model"], [tome[0], 0])


class Img2ImgGraph(unittest.TestCase):
    def test_init_image_is_encoded_and_denoise_applied(self):
        spec = RenderSpec(prompt="smiling", checkpoint=PERSON_CKPT, denoise=0.45, seed=77)
        g, seed = BACKEND.build_img2img(spec, "init.png")
        self.assertEqual(seed, 77)
        self.assertEqual(inputs_of(g, "LoadImage")["image"], "init.png")
        self.assertEqual(inputs_of(g, "VAEEncode")["pixels"], ["4", 0])
        ks = inputs_of(g, "KSampler")
        self.assertEqual(ks["latent_image"], ["41", 0])
        self.assertEqual(ks["denoise"], 0.45)
        self.assertEqual(find(g, "EmptyLatentImage"), [])     # img2img 는 빈 잠재를 쓰면 안 된다


class MetaPayload(unittest.TestCase):
    def test_keys_match_a1111_meta_contract(self):
        # _render_meta() 가 이 키들로 사이드카/EXIF 를 쓴다. 이름이 바뀌면 메타가 조용히 빈다.
        spec = RenderSpec(prompt="p", negative_prompt="n", checkpoint=PERSON_CKPT,
                          width=728, height=1104, steps=20, cfg_scale=7, seed=5)
        m = spec.meta_payload()
        for key in ("prompt", "negative_prompt", "steps", "sampler_name", "cfg_scale",
                    "width", "height", "seed"):
            self.assertIn(key, m)
        self.assertEqual(m["sampler_name"], "DPM++ 2M Karras")   # A1111 표기 그대로 기록


@unittest.skipUnless(LIVE, "ComfyUI(:8188) 미가동 — 스모크 렌더 생략")
class LiveSmoke(unittest.TestCase):
    def test_vram_reports_megabytes(self):
        v = BACKEND.vram()
        self.assertGreater(v["total_mb"], 1000)
        self.assertGreaterEqual(v["free_mb"], 0)
        self.assertEqual(v["used_mb"], v["total_mb"] - v["free_mb"])

    def test_small_render_returns_png_bytes(self):
        spec = RenderSpec(prompt="1girl, standing, plain background",
                          negative_prompt="lowres, bad anatomy",
                          checkpoint=PERSON_CKPT, width=384, height=512, steps=12,
                          seed=1234, kind="test")
        out = BACKEND.txt2img(spec, timeout=300)
        self.assertEqual(len(out["images"]), 1)
        self.assertTrue(out["images"][0].startswith(b"\x89PNG"))
        self.assertEqual(out["seed"], 1234)


if __name__ == "__main__":
    unittest.main(verbosity=2)
