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
    global _scene_state

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
                        remover = Remover(mode="base")
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
                    _scene_state["layers"] = []  # clear layers on new background
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
            logger.info(f"Illustration generated: {filename}")
        else:
            with _lock:
                _scene_state["generating"].update({
                    "status": "error",
                    "error": "No images in SD response",
                })
    except requests.exceptions.ConnectionError:
        logger.warning("SD WebUI not reachable, falling back to Cairo")
        _cairo_fallback(illustration_type, name, position, turn_count, distance, size_class)
    except Exception as e:
        logger.warning(f"SD generation failed ({e}), falling back to Cairo")
        _cairo_fallback(illustration_type, name, position, turn_count, distance, size_class)


def _cairo_fallback(illustration_type, name, position, turn_count, distance=0, size_class="close"):
    """Generate Cairo fallback illustration when SD is unavailable."""
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
            return {"started": True, "type": illustration_type, "source": "cairo"}

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
            return {"started": True, "type": illustration_type, "source": "cairo"}
    except Exception as e:
        logger.error(f"Cairo fallback failed: {e}")
        return {"skipped": True, "reason": f"Cairo fallback failed: {e}"}


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


def _find_existing_image(illustration_type, name):
    """Check if a reusable image already exists for this name."""
    if not name:
        return None
    safe_name = name.replace(" ", "_")

    # Check SD images first (higher quality)
    search_dirs = []
    if illustration_type == "portrait":
        search_dirs = [SD_PORTRAITS_DIR, os.path.join(BASE_DIR, "static", "portraits", "pixel")]
    else:
        search_dirs = [SD_ILLUSTRATIONS_DIR, os.path.join(BASE_DIR, "static", "illustrations", "pixel")]

    for search_dir in search_dirs:
        if not os.path.exists(search_dir):
            continue
        for f in os.listdir(search_dir):
            fname_lower = f.lower()
            name_lower = safe_name.lower()
            if name_lower in fname_lower and (f.endswith(".webp") or f.endswith(".png")):
                return os.path.join(search_dir, f)
    return None


def request_illustration(illustration_type, prompt, negative_prompt="", turn_count=0, position="center", name="", distance=0, size_class="close"):
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

    # 3. SD OFF → Cairo fallback
    if not is_sd_enabled():
        return _cairo_fallback(illustration_type, name, position, turn_count, distance, size_class)

    # 4. SD generation
    with _lock:
        if _scene_state["generating"]["status"] == "generating":
            return {"skipped": True, "reason": "Generation already in progress"}

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

    return {"started": True, "type": illustration_type}
