import base64
import json
import logging
import os
import threading
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SD_ILLUSTRATIONS_DIR = os.path.join(BASE_DIR, "static", "illustrations", "sd")
SD_PORTRAITS_DIR = os.path.join(BASE_DIR, "static", "portraits", "sd")
CURRENT_SESSION_PATH = os.path.join(BASE_DIR, "current_session.json")
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


def _generate_worker(illustration_type, prompt, negative_prompt, turn_count, position, name):
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
                    remover = Remover(mode="fast")
                    img = remover.process(img, type="rgba")
                except Exception as e:
                    logger.warning(f"Background removal failed, saving as-is: {e}")
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
        with _lock:
            _scene_state["generating"].update({
                "status": "error",
                "error": "SD WebUI not reachable at port 7860",
            })
    except Exception as e:
        logger.error(f"Illustration generation failed: {e}")
        with _lock:
            _scene_state["generating"].update({
                "status": "error",
                "error": str(e),
            })


def request_illustration(illustration_type, prompt, negative_prompt="", turn_count=0, position="center", name=""):
    global _scene_state

    if not is_sd_enabled():
        return {"skipped": True, "reason": "sd_illustration is disabled"}

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
        args=(illustration_type, prompt, negative_prompt, turn_count, position, name),
        daemon=True,
    )
    thread.start()

    return {"started": True, "type": illustration_type}
