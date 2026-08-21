import base64
import json
import logging
import os
import subprocess
import threading
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SD_ILLUSTRATIONS_DIR = os.path.join(BASE_DIR, "static", "illustrations", "sd")
SD_PORTRAITS_DIR = os.path.join(BASE_DIR, "static", "portraits", "sd")
# Shared NPC sprite pool — reused across ALL chats (scenario-independent). Holds transparent
# sprites for present characters/NPCs incl. non-human (objects, animals) for VN-mode display.
SD_NPC_DIR = os.path.join(BASE_DIR, "static", "portraits", "npc")
CURRENT_SESSION_PATH = os.path.join(BASE_DIR, "data", "current_session.json")
SD_API_URL = "http://127.0.0.1:7860"
# Minimum free VRAM (MB) required to start a NEW SD render. On an 8GB card SD and the local
# LLM (ollama) can't both fit; if the LLM holds the VRAM, free drops well below this and we
# skip SD generation (keep the placeholder/emoji) instead of OOMing or thrashing to CPU.
MIN_SD_FREE_MB = int(os.environ.get("SD_MIN_FREE_MB", "3000"))

# transparent-background Remover: run on CPU by default so it holds ~0 GPU VRAM (frees ~2GB for
# SD on an 8GB card, where the resident InSPyReNet model was the main competitor). Cached as a
# lazy singleton — the old code re-created Remover() on every call (1-3s model load each) and the
# torch CUDA caching allocator never returned the VRAM. Set SD_REMOVER_DEVICE=cuda for GPU speed
# when VRAM is plentiful.
_REMOVER = None
_REMOVER_DEVICE = os.environ.get("SD_REMOVER_DEVICE", "cpu")


def _get_remover():
    """Lazy singleton transparent-background Remover (CPU by default; env-overridable)."""
    global _REMOVER
    if _REMOVER is None:
        from transparent_background import Remover
        try:
            _REMOVER = Remover(device=_REMOVER_DEVICE)
        except TypeError:
            _REMOVER = Remover()  # older lib without the device kwarg
        logger.info("transparent-background Remover loaded (device=%s)", _REMOVER_DEVICE)
    return _REMOVER


_lock = threading.Lock()
_scene_state = {
    "background": None,
    "layers": [],
    "generating": {
        "status": "idle",
        "type": None,
        "prompt": None,
        "error": None,
        "started_at": None,
    },
}
# 중복 SD 생성 방지: 현재 SD 생성 진행 중인 (type, name) 세트
_pending_sd = set()
_pending_sd_lock = threading.Lock()


def is_sd_enabled():
    try:
        with open(CURRENT_SESSION_PATH, "r", encoding="utf-8") as f:
            session = json.load(f)
        return session.get("sd_illustration", False)
    except (FileNotFoundError, json.JSONDecodeError):
        return False


def free_vram_mb():
    """가장 여유 있는 GPU의 free VRAM(MB). nvidia-smi 없거나 실패하면 None(=측정 불가)."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5)
        vals = [int(x.strip()) for x in out.stdout.splitlines() if x.strip().isdigit()]
        return max(vals) if vals else None
    except Exception:
        return None


def sd_vram_ok(min_mb=None):
    """SD 신규 렌더에 충분한 free VRAM이 있는지. 측정 불가(nvidia-smi 없음)면 True(허용).
    로컬 LLM이 VRAM을 점유 중이면 free가 낮아져 False → SD 생성 스킵(경합 방지)."""
    free = free_vram_mb()
    if free is None:
        return True
    return free >= (MIN_SD_FREE_MB if min_mb is None else min_mb)


def vram_breakdown():
    """VRAM 부족 시 '뭐가 얼마씩 점유하는지' 내역을 반환.
    SD(torch)/ollama 로드 모델은 각 API로 정확히, 나머지는 '기타'로 집계. summary는 사람이 읽는 한 줄."""
    info = {"total_mb": None, "used_mb": None, "free_mb": free_vram_mb(), "consumers": []}
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total,memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5)
        t, u = out.stdout.splitlines()[0].split(",")
        info["total_mb"], info["used_mb"] = int(t), int(u)
    except Exception:
        pass
    accounted = 0
    try:  # SD WebUI torch 점유
        m = requests.get(f"{SD_API_URL}/sdapi/v1/memory", timeout=4).json()
        used = m.get("cuda", {}).get("system", {}).get("used")
        if used:
            mb = round(used / 1048576)
            info["consumers"].append({"name": "SD WebUI(torch)", "mb": mb}); accounted += mb
    except Exception:
        pass
    try:  # ollama 로드 모델(로컬 LLM)
        d = requests.get("http://127.0.0.1:11434/api/ps", timeout=4).json()
        for mo in d.get("models", []):
            mb = round(mo.get("size_vram", 0) / 1048576)
            if mb:
                info["consumers"].append({"name": f"ollama[{mo.get('name')}]", "mb": mb}); accounted += mb
    except Exception:
        pass
    if info["used_mb"] is not None and accounted:
        other = info["used_mb"] - accounted
        if other > 50:
            info["consumers"].append({"name": "기타(데스크톱 등)", "mb": other})
    parts = [f"{c['name']} {c['mb']}MB" for c in sorted(info["consumers"], key=lambda x: -x["mb"])]
    info["summary"] = (f"free {info['free_mb']}MB / used {info['used_mb']}MB / total {info['total_mb']}MB"
                       + ((" — " + ", ".join(parts)) if parts else ""))
    return info


def get_scene_state():
    with _lock:
        return dict(_scene_state)


def set_scene_state(background=None, layers=None):
    """외부에서 저장된 scene 정보로 복원할 때 사용"""
    with _lock:
        if background is not None:
            _scene_state["background"] = background
        if layers is not None:
            _scene_state["layers"] = layers
        _scene_state["generating"]["status"] = "idle"


_game_state_lock = threading.Lock()

def _sync_scene_to_game_state():
    """_scene_state를 game_state.json의 current_scene에 동기화 (atomic write)"""
    try:
        with _lock:
            scene_snapshot = {
                "background": _scene_state.get("background"),
                "layers": list(_scene_state.get("layers", [])),
            }
        gs_path = os.path.join(BASE_DIR, "data", "game_state.json")
        with _game_state_lock:
            with open(gs_path, "r", encoding="utf-8") as f:
                state = json.load(f)
            state["current_scene"] = scene_snapshot
            tmp_path = gs_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, gs_path)
    except Exception as e:
        logger.warning(f"Failed to sync scene to game_state: {e}")


def clear_scene():
    """Clear all layers and background."""
    with _lock:
        _scene_state["background"] = None
        _scene_state["layers"] = []


def remove_layer(name):
    """Remove a specific layer by name."""
    with _lock:
        _scene_state["layers"] = [l for l in _scene_state["layers"] if l.get("name") != name]


def _build_payload(illustration_type, prompt, negative_prompt, seed=-1):
    sizes = {
        "portrait": (384, 512),
        "sprite": (728, 1104),   # 1.2x of the Seraphina reference (608x920), full-body VN sprites
        "background": (896, 512),
        "scene": (896, 512),
        "object": (256, 256),
    }
    w, h = sizes.get(illustration_type, (512, 512))

    default_neg = "lowres, bad anatomy, bad hands, text, watermark, worst quality, low quality"
    if illustration_type in ("portrait", "object", "sprite"):
        default_neg += ", detailed background, scenery, landscape"
    if illustration_type == "sprite":
        # discourage tight framing so the whole body (at least knee-up) is shown
        default_neg += ", close-up, cropped, out of frame, upper body only"
    neg_prompt = negative_prompt or default_neg

    return {
        "prompt": prompt,
        "negative_prompt": neg_prompt,
        "steps": 20,
        "sampler_name": "DPM++ 2M Karras",
        "width": w,
        "height": h,
        "cfg_scale": 7,
        "batch_size": 1,
        "n_iter": 1,
        "seed": seed,   # -1 = random; a fixed int keeps NPC expressions visually consistent
        "alwayson_scripts": {
            "random": {"args": [False]}
        },
    }


def _generate_worker(illustration_type, prompt, negative_prompt, turn_count, position, name, distance=0, size_class="close"):
    """SD 백그라운드 생성 워커. Skia 플레이스홀더가 이미 존재하므로,
    SD 실패 시 추가 폴백 없이 Skia 이미지를 유지한다.
    SD 성공 시 같은 경로에 고품질 이미지를 덮어쓰고 scene_state를 갱신한다."""
    global _scene_state
    pending_key = (illustration_type, name)

    try:
        # Ensure correct model is loaded
        try:
            opts = requests.get(f"{SD_API_URL}/sdapi/v1/options", timeout=10).json()
            if "dreamshaper_8" not in opts.get("sd_model_checkpoint", ""):
                requests.post(
                    f"{SD_API_URL}/sdapi/v1/options",
                    json={"sd_model_checkpoint": "dreamshaper_8.safetensors"},
                    timeout=120,
                )
        except Exception:
            pass  # proceed anyway with whatever model is loaded

        payload = _build_payload(illustration_type, prompt, negative_prompt)
        response = requests.post(
            f"{SD_API_URL}/sdapi/v1/txt2img",
            json=payload,
            timeout=600,
        )
        response.raise_for_status()
        result = response.json()

        if result.get("images"):
            img_data = base64.b64decode(result["images"][0])
            if illustration_type == "portrait":
                save_dir = SD_PORTRAITS_DIR
            else:
                save_dir = SD_ILLUSTRATIONS_DIR
            os.makedirs(save_dir, exist_ok=True)

            # Reusable naming: use name (mandatory for reuse), fallback to location from session
            if name:
                safe_name = name.replace(" ", "_")
            else:
                # location에서 이름 추출 (타임스탬프 사용 금지 — 재활용 불가)
                try:
                    with open(os.path.join(BASE_DIR, "data", "current_session.json"), "r", encoding="utf-8") as _sf:
                        _sess = json.load(_sf)
                    safe_name = _sess.get("chapter_name", "") or "unnamed"
                except Exception:
                    safe_name = "unnamed"
                safe_name = safe_name.replace(" ", "_")
                logger.warning(f"SD generation without name — using '{safe_name}'. Always provide a name for reuse!")
            filename = f"{illustration_type}_{safe_name}.webp"
            # 같은 이름의 기존 파일이 있으면 덮어쓰기 (중복 방지)
            existing_same = os.path.join(save_dir, filename)
            if os.path.exists(existing_same):
                logger.info(f"Overwriting existing SD image: {filename}")
            filepath = os.path.join(save_dir, filename)

            # Convert to WebP, remove background for portraits/objects
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(img_data)).convert("RGB")

            if illustration_type in ("portrait", "object"):
                # Save original (before background removal)
                if illustration_type == "portrait":
                    original_dir = os.path.join(BASE_DIR, "static", "portraits", "original")
                else:  # object
                    original_dir = os.path.join(BASE_DIR, "static", "illustrations", "original")
                os.makedirs(original_dir, exist_ok=True)
                original_path = os.path.join(original_dir, f"{safe_name}.webp")
                img.save(original_path, "WEBP", quality=95)
                logger.info(f"Original {illustration_type} saved: {original_path}")

                # Remove background for compositing on any scene
                try:
                    from transparent_background import Remover
                except ImportError as e:
                    logger.error(f"transparent-background library import failed: {e}. "
                                 "Portraits will have opaque backgrounds. "
                                 "Install with: pip install transparent-background")
                    Remover = None
                try:
                    if Remover is not None:
                        import numpy as np
                        remover = _get_remover()
                        result = remover.process(img, type="rgba")
                        if isinstance(result, np.ndarray):
                            img = Image.fromarray(result)
                        else:
                            img = result
                    else:
                        img = img.convert("RGBA")
                except Exception as e:
                    logger.warning(f"Background removal processing failed, saving as-is: {e}")
                    img = img.convert("RGBA")
                img.save(filepath, "WEBP", quality=90)
            else:
                img.save(filepath, "WEBP", quality=90)

            if illustration_type == "portrait":
                image_url = f"/static/portraits/sd/{filename}"
            else:
                image_url = f"/static/illustrations/sd/{filename}"

            with _lock:
                if illustration_type == "background":
                    _scene_state["background"] = image_url
                    # 레이어는 유지 — 배경 교체(SD 완료)로 NPC 레이어가 사라지면 안 됨
                else:
                    # Remove existing layer with same name if any
                    _scene_state["layers"] = [l for l in _scene_state["layers"] if l.get("name") != name]
                    _scene_state["layers"].append({
                        "type": illustration_type,
                        "image": image_url,
                        "position": position,
                        "name": name,
                        "distance": distance,
                        "size_class": size_class,
                    })
                _scene_state["generating"]["status"] = "idle"
                _scene_state["generating"]["error"] = None
            logger.info(f"SD image generated (replacing Skia placeholder): {filename}")
            # game_state.json의 current_scene 갱신
            _sync_scene_to_game_state()
        else:
            logger.warning("No images in SD response — Skia placeholder retained")
            with _lock:
                _scene_state["generating"].update({
                    "status": "idle",
                    "error": "No images in SD response (Skia placeholder retained)",
                })
    except requests.exceptions.ConnectionError:
        logger.warning("SD WebUI not reachable — Skia placeholder retained")
        with _lock:
            _scene_state["generating"]["status"] = "idle"
    except Exception as e:
        logger.warning(f"SD generation failed ({e}) — Skia placeholder retained")
        with _lock:
            _scene_state["generating"]["status"] = "idle"
    finally:
        # 중복 생성 방지 플래그 해제
        with _pending_sd_lock:
            _pending_sd.discard(pending_key)


def _skia_placeholder(illustration_type, name, position, turn_count, distance=0, size_class="close"):
    """Skia로 즉시 플레이스홀더 이미지를 생성한다.
    반환값: {"started": True, "image_url": ..., "output_path": ..., "source": "skia"}
    SD가 나중에 같은 output_path에 덮어쓰기할 수 있다.
    """
    try:
        from core.map_generator import MapGenerator
        gen = MapGenerator()

        if illustration_type == "background":
            filepath = gen.generate_scene_background(name or "default")
            image_url = filepath.replace(os.sep, "/").split("static/")[-1]
            image_url = f"/static/{image_url}"
            with _lock:
                _scene_state["background"] = image_url
                _scene_state["layers"] = []
                _scene_state["generating"]["status"] = "idle"
            _sync_scene_to_game_state()
            return {"started": True, "type": illustration_type, "source": "skia",
                    "image_url": image_url, "output_path": filepath}

        elif illustration_type in ("portrait", "object"):
            filepath = gen.generate_scene_element(illustration_type, name or "unknown")
            image_url = filepath.replace(os.sep, "/").split("static/")[-1]
            image_url = f"/static/{image_url}"
            with _lock:
                _scene_state["layers"] = [l for l in _scene_state["layers"] if l.get("name") != name]
                _scene_state["layers"].append({
                    "type": illustration_type,
                    "image": image_url,
                    "position": position,
                    "name": name,
                    "distance": distance,
                    "size_class": size_class,
                })
                _scene_state["generating"]["status"] = "idle"
            _sync_scene_to_game_state()
            return {"started": True, "type": illustration_type, "source": "skia",
                    "image_url": image_url, "output_path": filepath}
    except Exception as e:
        logger.error(f"Skia placeholder failed: {e}")
        return {"skipped": True, "reason": f"Skia placeholder failed: {e}"}


def _build_portrait_prompt_from_entity(name):
    """Build SD prompt from NPC entity appearance data."""
    # Search all scenario entity directories
    entities_dir = os.path.join(BASE_DIR, "entities")
    for scenario_dir in os.listdir(entities_dir) if os.path.exists(entities_dir) else []:
        npcs_dir = os.path.join(entities_dir, scenario_dir, "npcs")
        if not os.path.exists(npcs_dir):
            continue
        for f in os.listdir(npcs_dir):
            filepath = os.path.join(npcs_dir, f)
            try:
                with open(filepath, "r", encoding="utf-8") as fh:
                    npc = json.load(fh)
                if npc.get("name") == name:
                    return _appearance_to_prompt(npc)
            except Exception:
                continue

    # Also check player entities
    for scenario_dir in os.listdir(entities_dir) if os.path.exists(entities_dir) else []:
        players_dir = os.path.join(entities_dir, scenario_dir, "players")
        if not os.path.exists(players_dir):
            continue
        for f in os.listdir(players_dir):
            filepath = os.path.join(players_dir, f)
            try:
                with open(filepath, "r", encoding="utf-8") as fh:
                    player = json.load(fh)
                if player.get("name") == name:
                    return _appearance_to_prompt(player)
            except Exception:
                continue

    # Also check object entities
    for scenario_dir in os.listdir(entities_dir) if os.path.exists(entities_dir) else []:
        objects_dir = os.path.join(entities_dir, scenario_dir, "objects")
        if not os.path.exists(objects_dir):
            continue
        for f in os.listdir(objects_dir):
            filepath = os.path.join(objects_dir, f)
            try:
                with open(filepath, "r", encoding="utf-8") as fh:
                    obj = json.load(fh)
                if obj.get("name") == name:
                    desc = obj.get("description", name)
                    obj_type = obj.get("type", "object")
                    return f"fantasy {obj_type}, {desc}, simple dark background, no people, no characters, masterpiece, best quality"
            except Exception:
                continue

    return ""


def _appearance_to_prompt(entity):
    """Convert entity appearance dict to SD-compatible English prompt."""
    import re

    parts = []

    race = entity.get("race", "인간")
    race_map = {
        "인간": "human",
        "엘프": "elf, pointed ears",
        "드워프": "dwarf, short stature, thick beard",
        "오크": "orc, green skin, tusks, muscular",
        "수인": "beast-person, animal features",
        "슬라임": "slime creature, translucent gelatinous body",
        "골렘": "stone golem, massive rocky body, glowing runes",
        "늑대": "wolf, gray fur, four legs, fangs",
        "말": "horse, brown fur, four legs, hooves, mane",
        "고블린": "goblin, small green creature, pointed ears",
    }
    parts.append(race_map.get(race, race))

    appearance = entity.get("appearance", {})
    if appearance:
        # Korean to English keyword translation
        kr_to_en = {
            # Age
            "10대": "teenager", "20대": "young adult in 20s", "30대": "adult in 30s",
            "40대": "middle aged in 40s", "50대": "older adult in 50s", "60대": "elderly in 60s",
            "성체": "adult",
            # Build
            "다부진": "sturdy build", "날씬한": "slim", "근육질": "muscular",
            "튼튼한": "sturdy", "작은": "small", "거대한": "massive", "큰": "large",
            # Skin/fur
            "갈색": "brown", "검은": "black", "흰": "white", "밝은": "light",
            "짙은": "dark", "녹색": "green", "회색": "gray", "붉은": "red",
            "그을린": "tanned", "창백한": "pale",
            # Hair
            "머리": "hair", "갈기": "mane", "털": "fur", "단발": "short hair",
            "긴": "long", "짧은": "short", "묶어": "tied up", "올림": "updo",
            # Face
            "주름": "wrinkles", "날카로운": "sharp", "온순한": "gentle",
            "눈": "eyes", "턱수염": "beard", "수염": "beard",
            "호기심": "curious",
            # Outfit
            "가죽": "leather", "갑옷": "armor", "로브": "robe", "조끼": "vest",
            "바지": "pants", "부츠": "boots", "외투": "coat", "치마": "skirt",
            "마구": "harness", "고삐": "reins", "안장": "saddle",
            # General
            "낡은": "worn", "오래된": "old", "새": "new", "화려한": "ornate",
            "단순한": "simple", "붕대": "bandage", "절뚝": "limping",
        }

        def translate_field(text):
            """Simple keyword-based Korean to English translation."""
            if not text:
                return ""
            result = text
            for kr, en in kr_to_en.items():
                result = result.replace(kr, en)
            # Remove any remaining Korean characters (they'll confuse SD)
            # Keep English, numbers, punctuation, spaces
            cleaned = re.sub(r'[가-힣]+', '', result).strip()
            # Clean up multiple spaces/commas
            cleaned = re.sub(r'\s+', ' ', cleaned)
            cleaned = re.sub(r',\s*,', ',', cleaned)
            cleaned = cleaned.strip(' ,')
            return cleaned

        # Gender prefix (중요: SD가 성별을 정확히 생성하도록)
        gender = appearance.get("gender", "")
        if gender == "female":
            parts.insert(0, "1woman, female")
        elif gender == "male":
            parts.insert(0, "1man, male")

        for field in ["age", "build", "skin", "hair", "face", "outfit", "notable"]:
            val = appearance.get(field, "")
            translated = translate_field(val)
            if translated:
                parts.append(translated)

    # Style keywords
    parts.extend(["fantasy", "semi-realistic", "upper body portrait", "simple background", "masterpiece", "best quality"])

    prompt = ", ".join(p for p in parts if p)
    logger.info(f"Auto-generated portrait prompt for '{entity.get('name', '?')}': {prompt[:150]}...")
    return prompt


def _get_ko_name_sd(en_name):
    """ko.json에서 영어→한국어 이름 변환 (sd_generator용)."""
    ko_path = os.path.join(BASE_DIR, "lang", "ko.json")
    try:
        with open(ko_path, "r", encoding="utf-8") as f:
            ko = json.load(f)
        return ko.get("npcs", {}).get(en_name, "") or ko.get("creatures", {}).get(en_name, "")
    except Exception:
        return ""


def _find_existing_image(illustration_type, name):
    """Check if a reusable image already exists for this name.
    Searches both English and Korean (ko.json) names."""
    if not name:
        return None
    safe_name = name.replace(" ", "_")
    ko_name = _get_ko_name_sd(name)

    # Check SD images first (higher quality)
    search_dirs = []
    if illustration_type == "portrait":
        search_dirs = [SD_PORTRAITS_DIR, os.path.join(BASE_DIR, "static", "portraits", "pixel")]
    else:
        search_dirs = [SD_ILLUSTRATIONS_DIR, os.path.join(BASE_DIR, "static", "illustrations", "pixel")]

    search_names = [safe_name.lower()]
    if ko_name:
        search_names.append(ko_name.lower())

    for search_dir in search_dirs:
        if not os.path.exists(search_dir):
            continue
        # SD ON일 때 pixel 이미지는 재활용하지 않음 (SD 생성 트리거 필요)
        # pixel 이미지는 _skia_placeholder에서 표시용으로 사용되지만, _find_existing_image에서는 skip
        if is_sd_enabled() and os.sep + "pixel" in search_dir:
            continue
        for f in os.listdir(search_dir):
            fname_lower = f.lower()
            for try_name in search_names:
                if try_name in fname_lower and (f.endswith(".webp") or f.endswith(".png")):
                    return os.path.join(search_dir, f)
    return None


def remove_portrait_background(image_path):
    """초상화/오브젝트 이미지의 배경을 제거한다. 이미 투명이면 스킵."""
    try:
        from PIL import Image
        img = Image.open(image_path)
        # 이미 RGBA이고 투명 픽셀이 있으면 스킵
        if img.mode == "RGBA":
            extrema = img.split()[3].getextrema()
            if extrema[0] < 250:  # 알파 채널에 투명 부분이 있음
                return {"skipped": True, "reason": "already transparent"}

        img = img.convert("RGB")
        try:
            import numpy as np
            remover = _get_remover()
            result = remover.process(img, type="rgba")
            if isinstance(result, np.ndarray):
                img = Image.fromarray(result)
            else:
                img = result
            img.save(image_path, "WEBP", quality=90)
            logger.info(f"Background removed: {image_path}")
            return {"success": True, "path": image_path}
        except ImportError:
            return {"error": "transparent-background not installed"}
        except Exception as e:
            logger.warning(f"Background removal failed for {image_path}: {e}")
            return {"error": str(e)}
    except Exception as e:
        return {"error": str(e)}


def remove_all_portrait_backgrounds():
    """static/portraits/sd/ 내 모든 초상화의 배경을 제거한다."""
    results = {"processed": 0, "skipped": 0, "errors": []}
    portrait_dir = os.path.join(BASE_DIR, "static", "portraits", "sd")
    if not os.path.isdir(portrait_dir):
        return results
    for fname in os.listdir(portrait_dir):
        if not (fname.endswith(".webp") or fname.endswith(".png")):
            continue
        fpath = os.path.join(portrait_dir, fname)
        result = remove_portrait_background(fpath)
        if result.get("success"):
            results["processed"] += 1
        elif result.get("skipped"):
            results["skipped"] += 1
        else:
            results["errors"].append(f"{fname}: {result.get('error', '?')}")
    logger.info(f"Background removal batch: {results}")
    return results


# ---- similar-background reuse + rotation (avoid re-generating near-identical scenes) ----
import glob as _bg_glob, random as _bg_random, re as _bg_re

# NOTE: time/weather/season words are intentionally NOT here — they are discriminators
# (see _BG_TIME/_BG_WEATHER/_BG_SEASON), so they must survive tokenization.
_BG_STOP = set(("background scene the and of a an in on at with without "
                "wide shot art concept fantasy view image picture detailed "
                # style/quality/lighting boilerplate — NOT location. Shared across most
                # prompts, so they must not count toward place similarity (loc).
                "anime highly detail illustration render realistic photorealistic quality "
                "masterpiece lighting light lights bright warm soft glowing cozy clean tidy "
                "indoor ambient dramatic people person angle").split())

def _bg_tok(s):
    return set(w for w in _bg_re.split(r"[^a-z0-9]+", (s or "").lower()) if len(w) > 2 and w not in _BG_STOP)

def _bg_tokens_of(webp):
    """Tokens describing an existing background: prefer the prompt embedded in the WebP
    (EXIF ImageDescription), else a legacy sidecar .txt, else fall back to the filename."""
    try:
        from PIL import Image as _PILImage
        desc = _PILImage.open(webp).getexif().get(0x010e)   # 0x010e = ImageDescription
        if desc:
            return _bg_tok(desc)
    except Exception:
        pass
    side = os.path.splitext(webp)[0] + ".txt"
    if os.path.exists(side):
        try:
            with open(side, encoding="utf-8") as f:
                return _bg_tok(f.read())
        except Exception:
            pass
    base = os.path.basename(webp)
    if base.startswith("background_"):
        base = base[len("background_"):]
    return _bg_tok(base.rsplit(".", 1)[0].replace("_", " "))

# Time / weather / season vocab — these DISCRIMINATE a scene (a night scene must not
# reuse a day background). If both request and candidate name a category and they don't
# overlap, that's a conflict and the candidate is excluded.
_BG_TIME = set("day night dawn dusk morning evening noon midnight afternoon sunset sunrise twilight daytime nighttime".split())
_BG_WEATHER = set("clear sunny sunlit rain rainy storm stormy thunderstorm snow snowy blizzard fog foggy mist misty cloudy overcast windy".split())
_BG_SEASON = set("spring summer autumn fall winter".split())
_BG_ATTR = _BG_TIME | _BG_WEATHER | _BG_SEASON

def _bg_attrs(toks):
    return (toks & _BG_TIME, toks & _BG_WEATHER, toks & _BG_SEASON)

def _bg_conflict(a, b):
    for x, y in zip(a, b):
        if x and y and not (x & y):   # both specify this category but disagree
            return True
    return False

_bg_last_rot = {}

def _find_similar_background(name, prompt):
    """Find an existing background whose scene matches closely — same PLACE and a
    compatible time/weather/season — and rotate among those matches. A night scene will
    never reuse a day background; if no compatible one exists, returns None (-> generate)."""
    want = _bg_tok(name) | _bg_tok(prompt)
    if not want:
        return None
    want_attr = _bg_attrs(want)
    want_loc = want - _BG_ATTR
    scored = []
    for f in _bg_glob.glob(os.path.join(SD_ILLUSTRATIONS_DIR, "background_*.webp")):
        ftok = _bg_tokens_of(f)
        if _bg_conflict(want_attr, _bg_attrs(ftok)):
            continue                                   # e.g. request=night vs candidate=day
        loc = len((ftok - _BG_ATTR) & want_loc)        # place similarity (attrs excluded)
        if loc < 2:
            continue
        attr_match = sum(len(x & y) for x, y in zip(want_attr, _bg_attrs(ftok)))
        scored.append((loc + attr_match * 3, f))       # matching time/weather/season is weighted
    if not scored:
        return None
    scored.sort(key=lambda x: -x[0])
    top = scored[0][0]
    pool = [f for (o, f) in scored if o >= max(2, (top + 1) // 2)]
    key = tuple(sorted(os.path.basename(f) for f in pool))
    last = _bg_last_rot.get(key)
    choices = [f for f in pool if f != last] or pool
    chosen = _bg_random.choice(choices)
    _bg_last_rot[key] = chosen
    return chosen

def generate_scene_background_sd(name, prompt, negative_prompt=""):
    """SD-ONLY 배경 생성 (SillyTavern용 — Skia 없음).
    1) 비슷한 기존 배경이 있으면 그 중 하나를 '번갈아' 재활용(재생성 안 함).
    2) 없으면 SD로 '동기' 렌더 후 저장(+ 프롬프트 sidecar 저장).
    3) SD 불가면 {"ok": False} — 호출측은 기존 배경 유지.
    """
    # 1) 비슷한 배경 재활용(로테이션). 정확 일치도 여기 포함됨(토큰 겹침으로).
    sim = _find_similar_background(name, prompt)
    if sim:
        image_url = "/static/illustrations/sd/" + os.path.basename(sim)
        with _lock:
            _scene_state["background"] = image_url
        return {"reused": True, "rotated": True, "image": image_url}
    # 1b) 그래도 정확 일치가 있으면(토큰 부족 케이스) 재활용
    existing = _find_existing_image("background", name)
    if existing:
        image_url = "/static/" + existing.replace(os.sep, "/").split("static/")[-1]
        with _lock:
            _scene_state["background"] = image_url
        return {"reused": True, "image": image_url}
    if not is_sd_enabled():
        return {"ok": False, "reason": "sd_disabled"}
    if not sd_vram_ok():
        bd = vram_breakdown()
        logger.warning("SD 생성 스킵(low_vram, 기준 %dMB): %s", MIN_SD_FREE_MB, bd["summary"])
        return {"ok": False, "reason": "low_vram", "free_vram_mb": bd["free_mb"], "vram": bd}
    try:
        # 올바른 모델 로드 보장
        try:
            opts = requests.get(f"{SD_API_URL}/sdapi/v1/options", timeout=10).json()
            if "dreamshaper_8" not in opts.get("sd_model_checkpoint", ""):
                requests.post(f"{SD_API_URL}/sdapi/v1/options",
                              json={"sd_model_checkpoint": "dreamshaper_8.safetensors"}, timeout=180)
        except Exception:
            pass
        payload = _build_payload("background", prompt, negative_prompt)
        response = requests.post(f"{SD_API_URL}/sdapi/v1/txt2img", json=payload, timeout=600)
        response.raise_for_status()
        result = response.json()
        if not result.get("images"):
            return {"ok": False, "reason": "no_image"}
        import io
        from PIL import Image
        img_data = base64.b64decode(result["images"][0])
        os.makedirs(SD_ILLUSTRATIONS_DIR, exist_ok=True)
        safe_name = name.replace(" ", "_")
        filename = f"background_{safe_name}.webp"
        filepath = os.path.join(SD_ILLUSTRATIONS_DIR, filename)
        _img = Image.open(io.BytesIO(img_data)).convert("RGB")
        # Embed the scene name + prompt directly in the WebP (EXIF ImageDescription) so
        # future scenes can find this as a "similar" background and reuse it instead of
        # generating a near-duplicate — no separate .txt sidecar needed.
        try:
            _exif = _img.getexif()
            _exif[0x010e] = (name or "") + "\n" + (prompt or "")   # 0x010e = ImageDescription
            _img.save(filepath, "WEBP", quality=90, exif=_exif.tobytes())
        except Exception:
            _img.save(filepath, "WEBP", quality=90)
        image_url = f"/static/illustrations/sd/{filename}"
        with _lock:
            _scene_state["background"] = image_url
            _scene_state["generating"]["status"] = "idle"
        logger.info(f"SD-only background generated: {filename}")
        return {"ok": True, "image": image_url, "source": "sd"}
    except requests.exceptions.ConnectionError:
        return {"ok": False, "reason": "sd_unreachable"}
    except Exception as e:
        logger.warning(f"SD-only background failed: {e}")
        return {"ok": False, "reason": str(e)}


def request_illustration(illustration_type, prompt, negative_prompt="", turn_count=0, position="center", name="", distance=0, size_class="close"):
    """Skia 즉시 생성 + SD 백그라운드 교체 패턴.

    1. 기존 이미지가 있으면 재활용
    2. Skia로 즉시 플레이스홀더 생성 (화면이 바로 갱신됨)
    3. SD ON이면 백그라운드에서 고품질 이미지 생성 → 완료 시 덮어쓰기
       (웹 UI 2초 폴링으로 자동 감지)
    4. SD OFF이면 Skia 이미지만 유지
    """
    global _scene_state

    # 1. Check for existing reusable image
    existing = _find_existing_image(illustration_type, name)
    if existing:
        image_url = existing.replace(os.sep, "/").split("static/")[-1]
        image_url = f"/static/{image_url}"
        with _lock:
            if illustration_type == "background":
                _scene_state["background"] = image_url
                _scene_state["layers"] = []
            else:
                _scene_state["layers"] = [l for l in _scene_state["layers"] if l.get("name") != name]
                _scene_state["layers"].append({
                    "type": illustration_type,
                    "image": image_url,
                    "position": position,
                    "name": name,
                    "distance": distance,
                    "size_class": size_class,
                })
            _scene_state["generating"]["status"] = "idle"
        logger.info(f"Reusing existing image: {existing}")
        return {"reused": True, "type": illustration_type, "image": image_url}

    # 2. Auto-generate prompt from entity data if portrait/object and prompt is empty
    if illustration_type in ("portrait", "object") and not prompt and name:
        prompt = _build_portrait_prompt_from_entity(name)
        if not prompt:
            prompt = f"fantasy character portrait, {name}, simple background, masterpiece"

    # 3. Skia 즉시 생성 (SD ON/OFF 모두)
    skia_result = _skia_placeholder(illustration_type, name, position, turn_count, distance, size_class)
    if skia_result.get("skipped"):
        logger.warning(f"Skia placeholder failed: {skia_result.get('reason')}")
        # Skia도 실패하면 더 이상 할 수 없음
        return skia_result

    # 4. SD OFF → Skia 이미지만 유지하고 종료
    if not is_sd_enabled():
        logger.info(f"SD OFF — Skia placeholder only: {illustration_type}/{name}")
        return skia_result

    # 5. SD ON → 백그라운드에서 고품질 이미지 생성
    pending_key = (illustration_type, name)

    # 중복 SD 생성 방지
    with _pending_sd_lock:
        if pending_key in _pending_sd:
            logger.info(f"SD generation already pending for {pending_key} — Skia placeholder shown")
            return {**skia_result, "sd_status": "already_pending"}
        _pending_sd.add(pending_key)

    with _lock:
        _scene_state["generating"].update({
            "status": "generating",
            "type": illustration_type,
            "prompt": prompt,
            "error": None,
            "started_at": datetime.now().isoformat(),
        })

    thread = threading.Thread(
        target=_generate_worker,
        args=(illustration_type, prompt, negative_prompt, turn_count, position, name, distance, size_class),
        daemon=True,
    )
    thread.start()

    logger.info(f"Skia placeholder shown, SD generating in background: {illustration_type}/{name}")
    return {**skia_result, "sd_status": "generating"}


def _npc_safe_name(name):
    return "".join(c if (c.isalnum() or c in "-_") else "_" for c in (name or "npc").strip().lower()).strip("_") or "npc"


def _npc_sprite_path(name, expression="neutral"):
    """공용 NPC 스프라이트 경로. 인물별 폴더 + 표정별 파일 (ST 캐릭터카드와 동일 구조):
    static/portraits/npc/<이름>/<표정>.webp"""
    safe = _npc_safe_name(name)
    expr = "".join(c if c.isalnum() else "_" for c in (expression or "neutral").strip().lower()) or "neutral"
    return safe, expr, os.path.join(SD_NPC_DIR, safe, expr + ".webp")


def _npc_seed(name):
    """이름 기반 고정 seed — 같은 NPC의 모든 표정이 같은 얼굴/구도를 유지하도록."""
    import hashlib
    return int(hashlib.md5(_npc_safe_name(name).encode("utf-8")).hexdigest()[:7], 16)


def _norm_key(s):
    """이름 정규화: 소문자 + 영숫자만(공백/언더바/하이픈 제거). 대소문자·공백 차이를 흡수해
    수동으로 넣은 파일명(예: 'OLIVIA HAYES')과 조회 이름('Olivia Hayes')을 매칭한다."""
    return "".join(c for c in (s or "").lower() if c.isalnum())


def _name_match(a, b):
    """이름 정규화 매칭 강도: 2=정확 일치, 1=접두 일치(둘 중 하나가 다른 것의 접두어, 최소 4자),
    0=불일치. 트래커가 'abigail'로 줘도 폴더 'abigail_reed'를 잡도록(짧은 이름 대응)."""
    if a == b:
        return 2
    if len(a) >= 4 and len(b) >= 4 and (a.startswith(b) or b.startswith(a)):
        return 1
    return 0


def find_npc_sprite(name, expression="neutral"):
    """공용 NPC 폴더에서 (이름, 표정) 스프라이트를 관대하게 찾는다 — 모든 채팅 공유.
    정규 경로 → 이름 매칭(정확>접두). 인물 폴더의 요청 표정>neutral, 또는 수동 flat 파일(=neutral 베이스).
    사용자가 직접 넣은 'Olivia Hayes.webp' 같은 파일도 그대로 사용한다(이동/개명 안 함)."""
    safe, expr, path = _npc_sprite_path(name, expression)
    if os.path.exists(path):
        return "/static/portraits/npc/" + safe + "/" + expr + ".webp"
    if not os.path.isdir(SD_NPC_DIR):
        return None
    target = _norm_key(name)
    if not target:
        return None
    best, best_score = None, 0
    for entry in os.listdir(SD_NPC_DIR):
        full = os.path.join(SD_NPC_DIR, entry)
        url, score = None, 0
        # 인물 폴더 매칭 (한글/영어 폴더 모두) → 요청 표정 우선, 없으면 neutral
        if os.path.isdir(full):
            m = _name_match(_norm_key(entry), target)
            if m:
                for e in (expr, "neutral"):
                    p = os.path.join(full, e + ".webp")
                    if os.path.exists(p):
                        url = "/static/portraits/npc/" + entry + "/" + e + ".webp"
                        score = m * 10 + (5 if e == expr else 1)   # 정확>접두, 표정일치 가산
                        break
        # 수동으로 넣은 flat 파일 (npc_ 접두어 없는 것) = neutral 베이스
        elif os.path.isfile(full) and entry.lower().endswith((".webp", ".png")) and not entry.startswith("npc_"):
            m = _name_match(_norm_key(os.path.splitext(entry)[0]), target)
            if m:
                url = "/static/portraits/npc/" + entry
                score = m * 10
        if url and score > best_score:
            best, best_score = url, score
    return best


def _resolve_npc_dir(name):
    """이름 → 실제 인물 폴더 엔트리(정확 슬러그 우선, 없으면 이름 매칭). 없으면 None."""
    if not os.path.isdir(SD_NPC_DIR):
        return None
    safe = _npc_safe_name(name)
    if os.path.isdir(os.path.join(SD_NPC_DIR, safe)):
        return safe
    target = _norm_key(name)
    if not target:
        return None
    best, best_m = None, 0
    for entry in os.listdir(SD_NPC_DIR):
        if os.path.isdir(os.path.join(SD_NPC_DIR, entry)):
            m = _name_match(_norm_key(entry), target)
            if m and m > best_m:
                best, best_m = entry, m
    return best


def list_npc_variants(name):
    """보너스 외형 변형 목록: 인물 폴더의 var_<특징>.webp 파일들.
    반환 [{"feature": <특징>, "url": "/static/portraits/npc/<폴더>/var_<특징>.webp"}] (특징 정렬)."""
    folder = _resolve_npc_dir(name)
    if not folder:
        return []
    out = []
    fdir = os.path.join(SD_NPC_DIR, folder)
    try:
        for f in sorted(os.listdir(fdir)):
            low = f.lower()
            if low.startswith("var_") and low.endswith(".webp"):
                out.append({
                    "feature": f[4:-5],   # 'var_' 접두, '.webp' 확장 제거
                    "url": "/static/portraits/npc/" + folder + "/" + f,
                })
    except Exception:
        pass
    return out


# 표정 라벨 → SD 프롬프트에 넣을 표현구
_EXPR_PHRASE = {
    "neutral": "neutral calm expression",
    "joy": "happy smiling, joyful expression",
    "happy": "happy smiling expression",
    "anger": "angry, furious expression, frowning",
    "sadness": "sad, teary expression",
    "sad": "sad expression",
    "surprise": "surprised, wide eyes, shocked expression",
    "fear": "fearful, scared expression",
    "disgust": "disgusted expression",
    "annoyance": "annoyed, irritated expression",
    "embarrassment": "embarrassed, blushing expression",
    "love": "loving, affectionate expression, soft smile",
    "curiosity": "curious, intrigued expression",
}


def generate_npc_sprite(name, prompt, expression="neutral", negative_prompt=""):
    """공용 NPC 표정 스프라이트: (이름, 표정)별로 재활용/생성. 모든 채팅이 static/portraits/npc/
    를 공유한다. 사물/동물 등 비인간 포함. 이름 기반 고정 seed로 표정 간 일관성 유지.
    prompt 는 (프론트에서 만든) 영어 SD 프롬프트. 반환 {reused/ok, image} 또는 {ok:False}."""
    expression = (expression or "neutral").strip().lower()
    # 1) reuse-first: 정확히 이 (이름, 표정)이 있으면 재활용
    existing = find_npc_sprite(name, expression)
    if existing:
        return {"reused": True, "image": existing, "expression": expression}
    if not is_sd_enabled():
        return {"ok": False, "reason": "sd_disabled"}
    if not sd_vram_ok():
        bd = vram_breakdown()
        logger.warning("SD 생성 스킵(low_vram, 기준 %dMB): %s", MIN_SD_FREE_MB, bd["summary"])
        return {"ok": False, "reason": "low_vram", "free_vram_mb": bd["free_mb"], "vram": bd}
    try:
        try:
            opts = requests.get(f"{SD_API_URL}/sdapi/v1/options", timeout=10).json()
            if "dreamshaper_8" not in opts.get("sd_model_checkpoint", ""):
                requests.post(f"{SD_API_URL}/sdapi/v1/options",
                              json={"sd_model_checkpoint": "dreamshaper_8.safetensors"}, timeout=180)
        except Exception:
            pass
        expr_phrase = _EXPR_PHRASE.get(expression, expression + " expression")
        # 상반신 + 단색 배경(깔끔한 배경제거) + 표정. portrait 타입 negative에 배경 억제 포함.
        full_prompt = (prompt or (name or "character")) + ", " + expr_phrase + \
                      ", full body, standing, whole body visible from head to knees, plain solid background, character sprite, high quality"
        payload = _build_payload("sprite", full_prompt, negative_prompt, seed=_npc_seed(name))
        response = requests.post(f"{SD_API_URL}/sdapi/v1/txt2img", json=payload, timeout=600)
        response.raise_for_status()
        result = response.json()
        if not result.get("images"):
            return {"ok": False, "reason": "no_image"}
        import io
        from PIL import Image
        img_data = base64.b64decode(result["images"][0])
        _safe, _expr, filepath = _npc_sprite_path(name, expression)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)   # 인물별 폴더 생성
        img = Image.open(io.BytesIO(img_data)).convert("RGB")
        try:
            exif = img.getexif()
            exif[0x010e] = (name or "") + "|" + expression + "\n" + (prompt or "")
            img.save(filepath, "WEBP", quality=90, exif=exif.tobytes())
        except Exception:
            img.save(filepath, "WEBP", quality=90)
        remove_portrait_background(filepath)   # 투명 배경 (VN 배경 위 합성용)
        image_url = "/static/portraits/npc/" + _safe + "/" + _expr + ".webp"
        logger.info(f"NPC sprite generated: {os.path.basename(filepath)} (seed={_npc_seed(name)})")
        return {"ok": True, "image": image_url, "source": "sd", "expression": expression}
    except Exception as e:
        logger.error(f"generate_npc_sprite failed: {e}")
        return {"ok": False, "reason": str(e)}


def ingest_manual_npc_sprites():
    """사용자가 npc/ 루트에 직접 넣은 flat 이미지(배경 있음)를 처리한다:
    배경 제거(투명) → 인물 폴더 npc/<영어슬러그>/neutral.webp 로 이동. 재실행 안전.
    'npc_' 접두어(레거시 자동생성)와 이미 폴더 안의 파일은 건드리지 않는다."""
    from PIL import Image
    results = {"ingested": [], "skipped": []}
    if not os.path.isdir(SD_NPC_DIR):
        return results
    for entry in list(os.listdir(SD_NPC_DIR)):
        full = os.path.join(SD_NPC_DIR, entry)
        if not os.path.isfile(full):
            continue
        if entry.startswith("npc_"):
            continue
        if not entry.lower().endswith((".webp", ".png", ".jpg", ".jpeg")):
            continue
        base = os.path.splitext(entry)[0]
        safe = _npc_safe_name(base)
        npc_dir = os.path.join(SD_NPC_DIR, safe)
        target = os.path.join(npc_dir, "neutral.webp")
        try:
            os.makedirs(npc_dir, exist_ok=True)
            Image.open(full).convert("RGB").save(target, "WEBP", quality=92)
            remove_portrait_background(target)   # 투명화 (VN 배경 위 합성용)
            if os.path.abspath(full) != os.path.abspath(target):
                os.remove(full)   # 폴더로 이동 완료 → 원본 flat 제거
            results["ingested"].append({"file": entry, "key": safe})
            logger.info(f"NPC sprite ingested: {entry} -> {safe}/neutral.webp")
        except Exception as e:
            results["skipped"].append({"file": entry, "error": str(e)})
    return results


def _npc_url_to_path(url):
    """/static/... URL -> absolute file path (None if missing)."""
    if not url:
        return None
    p = os.path.join(BASE_DIR, str(url).lstrip("/").replace("/", os.sep))
    return p if os.path.exists(p) else None


def _subject_ratio(path):
    """Opaque-pixel ratio after background removal. ~1.0 = nothing was removed (probably not a
    character cutout), ~0.0 = removal ate everything. A real portrait lands in between."""
    from PIL import Image
    im = Image.open(path)
    if im.mode != "RGBA":
        return 1.0
    total = im.width * im.height
    if not total:
        return 0.0
    return sum(im.getchannel("A").histogram()[128:]) / total


def has_exact_npc_sprite(name, expression="neutral"):
    """EXACT (name, expression) file check. find_npc_sprite() is deliberately tolerant (falls back
    to neutral / prefix matches), which would make an expression look 'already present' and block
    expression rendering — callers deciding whether to RENDER must use this instead."""
    try:
        _safe, _expr, filepath = _npc_sprite_path(name, expression)
        return os.path.exists(filepath)
    except Exception:
        return False


def ingest_card_sprite(name, image_b64, force=False):
    """Use a SillyTavern character-card image as that character's BASE (neutral) sprite.

    '알맞은 이미지'만 채택한다 — scenario/logo cards (wide banners, text-only art) would look
    broken as a VN sprite, so we reject them and let SD generate instead:
      - aspect ratio must be portrait-ish (w/h <= 1.15)
      - after background removal the subject must cover 8%~92% of the frame
    Returns {ok, image, subject_ratio} or {ok: False, reason}.
    """
    import io
    from PIL import Image
    if not name or not image_b64:
        return {"ok": False, "reason": "name/image required"}
    try:
        raw = base64.b64decode(str(image_b64).split(",")[-1])
        img = Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception as e:
        return {"ok": False, "reason": f"decode failed: {e}"}

    if not force and img.height and (img.width / img.height) > 1.15:
        return {"ok": False, "reason": "not_portrait", "size": [img.width, img.height]}

    # Monochrome art = emblem/logo/document card (measured: SCF logo 0.0, Common Sense 0.0, while
    # real character cards land at 60~83 mean saturation). Those look broken as a VN sprite.
    try:
        from PIL import ImageStat
        sat = ImageStat.Stat(img.resize((128, 192)).convert("HSV").getchannel("S")).mean[0]
    except Exception:
        sat = 99.0
    if not force and sat < 12:
        return {"ok": False, "reason": "monochrome_logo", "saturation": round(sat, 1)}

    safe, expr, filepath = _npc_sprite_path(name, "neutral")
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    tmp = filepath + ".card_tmp.webp"
    img.save(tmp, "WEBP", quality=92)
    try:
        remove_portrait_background(tmp)
        ratio = _subject_ratio(tmp)
        if not force and not (0.08 <= ratio <= 0.92):
            os.remove(tmp)
            return {"ok": False, "reason": "no_clear_subject", "subject_ratio": round(ratio, 3)}
        os.replace(tmp, filepath)
    except Exception as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        return {"ok": False, "reason": str(e)}
    url = "/static/portraits/npc/" + safe + "/neutral.webp"
    logger.info("card sprite ingested: %s -> %s (subject=%.2f)", name, url, ratio)
    return {"ok": True, "image": url, "source": "card", "expression": "neutral",
            "subject_ratio": round(ratio, 3)}


def generate_expression_from_base(name, expression, prompt="", denoise=0.45):
    """Make an expression sprite from the character's existing NEUTRAL sprite via img2img, so the
    face/outfit/design stay recognizably the same character (txt2img would redraw a new person).
    Used for card-image-based characters and for NPC expression consistency."""
    base_url = find_npc_sprite(name, "neutral")
    base_path = _npc_url_to_path(base_url)
    if not base_path:
        return {"ok": False, "reason": "no_base_sprite"}
    if not is_sd_enabled():
        return {"ok": False, "reason": "sd_disabled"}
    if not sd_vram_ok():
        bd = vram_breakdown()
        logger.warning("SD 생성 스킵(low_vram, 기준 %dMB): %s", MIN_SD_FREE_MB, bd["summary"])
        return {"ok": False, "reason": "low_vram", "free_vram_mb": bd["free_mb"], "vram": bd}
    import io
    from PIL import Image
    try:
        base = Image.open(base_path).convert("RGB")   # flatten alpha for img2img
        buf = io.BytesIO()
        base.save(buf, "PNG")
        init_b64 = base64.b64encode(buf.getvalue()).decode()
        expr_phrase = _EXPR_PHRASE.get(expression, expression + " expression")
        payload = _build_payload("sprite", (prompt or name) + ", " + expr_phrase +
                                 ", same character, same outfit, plain solid background, character sprite",
                                 "", seed=_npc_seed(name))
        payload.update({"init_images": [init_b64], "denoising_strength": denoise,
                        "resize_mode": 1, "width": base.width, "height": base.height})
        r = requests.post(f"{SD_API_URL}/sdapi/v1/img2img", json=payload, timeout=600)
        r.raise_for_status()
        res = r.json()
        if not res.get("images"):
            return {"ok": False, "reason": "no_image"}
        safe, expr, filepath = _npc_sprite_path(name, expression)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        Image.open(io.BytesIO(base64.b64decode(res["images"][0]))).convert("RGB").save(
            filepath, "WEBP", quality=90)
        remove_portrait_background(filepath)
        url = "/static/portraits/npc/" + safe + "/" + expr + ".webp"
        logger.info("expression sprite (img2img) generated: %s", url)
        return {"ok": True, "image": url, "source": "img2img", "expression": expression}
    except Exception as e:
        logger.error("generate_expression_from_base failed: %s", e)
        return {"ok": False, "reason": str(e)}


def pre_generate_images(scenario_id):
    """시나리오 사전 이미지 생성 — 새 게임 시작 시 호출.
    챕터 배경 + 주요 NPC/플레이어 초상화를 미리 생성한다.
    SD OFF 시에도 Skia 폴백으로 생성.
    """
    import time

    scenario_path = os.path.join(BASE_DIR, "data", "scenario.json")
    game_state_path = os.path.join(BASE_DIR, "data", "game_state.json")

    try:
        with open(scenario_path, "r", encoding="utf-8") as f:
            scenario = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        logger.warning("pre_generate_images: scenario.json not found")
        return {"generated": 0, "skipped": 0, "errors": []}

    try:
        with open(game_state_path, "r", encoding="utf-8") as f:
            game_state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        game_state = {}

    results = {"generated": 0, "skipped": 0, "errors": []}

    # 1. 챕터 배경 생성
    chapters = scenario.get("chapters", [])
    chapter_themes = scenario.get("chapter_themes", {})
    for ch in chapters:
        ch_name = ch.get("map_area", ch.get("name", f"chapter_{ch.get('id', 0)}"))
        bg_name = ch_name.replace(" ", "_")

        # 이미 존재하면 스킵
        if _find_existing_image("background", bg_name):
            results["skipped"] += 1
            logger.info(f"Pre-gen skip (exists): background_{bg_name}")
            continue

        # 챕터 테마에서 프롬프트 힌트
        theme = chapter_themes.get(str(ch.get("id", 0)), {})
        bg_type = theme.get("bg_type", "")
        ch_desc = ch.get("description", "")

        prompt = f"fantasy landscape, {bg_type}, {ch_desc}, wide angle, landscape orientation, masterpiece, best quality"
        prompt = prompt.replace(",,", ",").strip(", ")

        logger.info(f"Pre-gen background: {bg_name}")
        result = request_illustration("background", prompt, name=bg_name)

        # 생성 대기 (SD는 비동기이므로 완료까지 대기)
        if result.get("started"):
            _wait_for_generation(timeout=120)
            results["generated"] += 1
        elif result.get("reused"):
            results["skipped"] += 1
        else:
            results["errors"].append(f"background_{bg_name}: {result}")

    # 2. NPC 초상화 생성
    entities_dir = os.path.join(BASE_DIR, "entities", scenario_id, "npcs")
    if os.path.isdir(entities_dir):
        for fname in sorted(os.listdir(entities_dir)):
            if not fname.endswith(".json"):
                continue
            filepath = os.path.join(entities_dir, fname)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    npc = json.load(f)
            except Exception:
                continue

            npc_name = npc.get("name", "")
            if not npc_name:
                continue

            if _find_existing_image("portrait", npc_name):
                results["skipped"] += 1
                logger.info(f"Pre-gen skip (exists): portrait_{npc_name}")
                continue

            # prompt는 빈 문자열 — request_illustration이 엔티티에서 자동 생성
            logger.info(f"Pre-gen portrait: {npc_name}")
            result = request_illustration("portrait", "", name=npc_name)

            if result.get("started"):
                _wait_for_generation(timeout=120)
                results["generated"] += 1
            elif result.get("reused"):
                results["skipped"] += 1
            else:
                results["errors"].append(f"portrait_{npc_name}: {result}")

    # 3. 플레이어 초상화 생성
    players_dir = os.path.join(BASE_DIR, "entities", scenario_id, "players")
    if os.path.isdir(players_dir):
        for fname in sorted(os.listdir(players_dir)):
            if not fname.endswith(".json"):
                continue
            filepath = os.path.join(players_dir, fname)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    player = json.load(f)
            except Exception:
                continue

            player_name = player.get("name", "")
            if not player_name:
                continue

            if _find_existing_image("portrait", player_name):
                results["skipped"] += 1
                logger.info(f"Pre-gen skip (exists): portrait_{player_name}")
                continue

            logger.info(f"Pre-gen portrait: {player_name}")
            result = request_illustration("portrait", "", name=player_name)

            if result.get("started"):
                _wait_for_generation(timeout=120)
                results["generated"] += 1
            elif result.get("reused"):
                results["skipped"] += 1
            else:
                results["errors"].append(f"portrait_{player_name}: {result}")

    logger.info(f"Pre-generation complete: {results}")
    return results


def _wait_for_generation(timeout=120):
    """SD 생성 완료 대기."""
    import time
    start = time.time()
    while time.time() - start < timeout:
        with _lock:
            status = _scene_state["generating"]["status"]
        if status != "generating":
            return True
        time.sleep(1)
    logger.warning(f"Pre-gen timeout after {timeout}s")
    return False
