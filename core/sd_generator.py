import base64
import json
import logging
import os
import threading
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SD_ILLUSTRATIONS_DIR = os.path.join(BASE_DIR, "static", "illustrations", "sd")
SD_PORTRAITS_DIR = os.path.join(BASE_DIR, "static", "portraits", "sd")
CURRENT_SESSION_PATH = os.path.join(BASE_DIR, "data", "current_session.json")
SD_API_URL = "http://127.0.0.1:7860"

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


def _build_payload(illustration_type, prompt, negative_prompt):
    sizes = {
        "portrait": (384, 512),
        "background": (896, 512),
        "scene": (896, 512),
        "object": (256, 256),
    }
    w, h = sizes.get(illustration_type, (512, 512))

    default_neg = "lowres, bad anatomy, bad hands, text, watermark, worst quality, low quality"
    if illustration_type in ("portrait", "object"):
        default_neg += ", detailed background, scenery, landscape"
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

            # Reusable naming: use name if provided, otherwise timestamp
            safe_name = name.replace(" ", "_") if name else datetime.now().strftime("%H%M%S")
            filename = f"{illustration_type}_{safe_name}.webp"
            filepath = os.path.join(save_dir, filename)

            # Convert to WebP, remove background for portraits/objects
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(img_data)).convert("RGB")

            if illustration_type in ("portrait", "object"):
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
                        remover = Remover()
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
        # SD ON일 때 pixel 디렉토리의 이미지는 재활용하지 않음 (SD 생성 트리거 필요)
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
            from transparent_background import Remover
            import numpy as np
            remover = Remover()
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
