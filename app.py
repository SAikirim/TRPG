import json
import os
from datetime import datetime

from flask import Flask, jsonify, render_template, request

from map_generator import MapGenerator
from save_manager import SaveManager
from sd_generator import request_illustration, get_scene_state, is_sd_enabled, clear_scene, remove_layer

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GAME_STATE_PATH = os.path.join(BASE_DIR, "game_state.json")


def load_game_state():
    with open(GAME_STATE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


save_manager = SaveManager()


def save_game_state(state):
    with open(GAME_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    # 자동 저장: 시나리오 ID 기반으로 슬롯 1에 항상 저장
    scenario_id = state.get("game_info", {}).get("scenario_id", "default")
    turn = state.get("turn_count", 0)
    save_manager.save_game(scenario_id, slot=1, description=f"자동 저장 (턴 {turn})")


def update_map_image():
    gen = MapGenerator()
    gen.save_map()


# Generate initial map on startup
update_map_image()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/game-state", methods=["GET"])
def get_game_state():
    state = load_game_state()
    return jsonify(state)


@app.route("/api/player-action", methods=["POST"])
def player_action():
    data = request.get_json()
    player_id = data.get("player_id")
    action = data.get("action")

    if not player_id or not action:
        return jsonify({"error": "player_id and action are required"}), 400

    state = load_game_state()

    player = None
    for p in state["players"]:
        if p["id"] == player_id:
            player = p
            break

    if not player:
        return jsonify({"error": "Player not found"}), 404

    state["turn_count"] += 1
    event = {
        "turn": state["turn_count"],
        "message": f"{player['name']}({player['class']})이(가) '{action}' 행동을 선택했다!",
        "timestamp": datetime.now().strftime("%H:%M:%S"),
    }
    state["events"].append(event)

    save_game_state(state)
    update_map_image()

    return jsonify({"success": True, "event": event, "turn": state["turn_count"]})


@app.route("/api/player-stats/<int:player_id>", methods=["GET"])
def player_stats(player_id):
    state = load_game_state()
    for p in state["players"]:
        if p["id"] == player_id:
            return jsonify(p)
    return jsonify({"error": "Player not found"}), 404


@app.route("/api/events", methods=["GET"])
def get_events():
    state = load_game_state()
    events = state.get("events", [])
    return jsonify(events[-20:])


@app.route("/api/gm-update", methods=["POST"])
def gm_update():
    data = request.get_json()
    state = load_game_state()

    description = data.get("description", "")
    narrative = data.get("narrative", "")

    # Apply player updates
    for pu in data.get("player_updates", []):
        for p in state["players"]:
            if p["id"] == pu["id"]:
                for key, val in pu.items():
                    if key != "id":
                        if key == "position" and isinstance(val, list):
                            p["position"] = val
                        elif key in ("hp", "mp"):
                            p[key] = max(0, min(val, p[f"max_{key}"]))
                        elif key == "status_effects":
                            p["status_effects"] = val
                        elif key == "inventory":
                            p["inventory"] = val
                break

    # Apply NPC updates
    for nu in data.get("npc_updates", []):
        for n in state["npcs"]:
            if n["id"] == nu["id"]:
                for key, val in nu.items():
                    if key != "id":
                        if key == "hp":
                            n["hp"] = max(0, val)
                            if n["hp"] <= 0:
                                n["status"] = "dead"
                        elif key == "position" and isinstance(val, list):
                            n["position"] = val
                        elif key == "status":
                            n["status"] = val
                break

    # Add new NPCs if provided
    for new_npc in data.get("new_npcs", []):
        state["npcs"].append(new_npc)

    state["turn_count"] += 1
    event = {
        "turn": state["turn_count"],
        "message": f"[GM] {description}",
        "narrative": narrative,
        "timestamp": datetime.now().strftime("%H:%M:%S"),
    }
    state["events"].append(event)

    # Update game status if provided
    if "game_status" in data:
        state["game_info"]["status"] = data["game_status"]

    save_game_state(state)
    update_map_image()

    # Handle illustration request
    illustration_req = data.get("illustration")
    ill_result = None
    if illustration_req:
        ill_result = request_illustration(
            illustration_type=illustration_req.get("type", "scene"),
            prompt=illustration_req.get("prompt", ""),
            negative_prompt=illustration_req.get("negative_prompt", ""),
            turn_count=state["turn_count"],
            position=illustration_req.get("position", "center"),
            name=illustration_req.get("name", ""),
        )

    # Handle scene management commands
    if data.get("clear_scene"):
        clear_scene()
    if data.get("remove_layer"):
        remove_layer(data["remove_layer"])

    return jsonify({"success": True, "event": event, "turn": state["turn_count"], "illustration": ill_result})


@app.route("/api/illustration", methods=["GET"])
def get_illustration():
    state = get_scene_state()
    state["enabled"] = is_sd_enabled()

    # Add default background based on current chapter
    game = load_game_state()
    chapter = game.get("game_info", {}).get("current_chapter", 1)
    chapter_bg_map = {
        1: {"sd": "/static/illustrations/sd/ch1_forest.png", "pixel": "/static/illustrations/pixel/forest.png"},
        2: {"sd": "/static/illustrations/sd/ch2_dungeon.png", "pixel": "/static/illustrations/pixel/dungeon.png"},
        3: {"sd": "/static/illustrations/sd/ch3_treasure.png", "pixel": "/static/illustrations/pixel/treasure.png"},
    }
    state["default_bg"] = chapter_bg_map.get(chapter, chapter_bg_map[1])
    state["current_chapter"] = chapter

    return jsonify(state)


@app.route("/api/illustration/clear", methods=["POST"])
def clear_illustration():
    clear_scene()
    return jsonify({"success": True})


@app.route("/api/illustration/toggle", methods=["POST"])
def toggle_illustration():
    session_path = os.path.join(BASE_DIR, "current_session.json")
    with open(session_path, "r", encoding="utf-8") as f:
        session = json.load(f)
    current = session.get("sd_illustration", False)
    session["sd_illustration"] = not current
    with open(session_path, "w", encoding="utf-8") as f:
        json.dump(session, f, ensure_ascii=False, indent=2)
    return jsonify({"sd_illustration": session["sd_illustration"]})


@app.route("/api/reset-game", methods=["POST"])
def reset_game():
    initial_path = os.path.join(BASE_DIR, "game_state_initial.json")
    if os.path.exists(initial_path):
        with open(initial_path, "r", encoding="utf-8") as f:
            state = json.load(f)
    else:
        state = load_game_state()
        state["turn_count"] = 0
        state["events"] = [
            {
                "turn": 0,
                "message": "게임이 초기화되었다! 모험가들이 숲의 입구에 다시 모였다.",
                "timestamp": datetime.now().strftime("%H:%M:%S"),
            }
        ]
        for p in state["players"]:
            p["hp"] = p["max_hp"]
            p["mp"] = p["max_mp"]
            p["status_effects"] = []
        for n in state["npcs"]:
            n["hp"] = n["max_hp"]
            n["status"] = "idle"

    save_game_state(state)
    update_map_image()
    return jsonify({"success": True, "message": "Game reset"})


@app.route("/api/load", methods=["POST"])
def load_game():
    data = request.get_json() or {}
    scenario_id = data.get("scenario_id", "default")
    slot = data.get("slot", 1)
    info = save_manager.load_game(scenario_id, slot)
    if info is None:
        return jsonify({"error": "Save not found"}), 404
    update_map_image()
    return jsonify({"success": True, "save_info": info})


@app.route("/api/saves", methods=["GET"])
def list_saves():
    scenario_id = request.args.get("scenario_id")
    saves = save_manager.list_saves(scenario_id)
    return jsonify(saves)


@app.route("/api/progress/<scenario_id>", methods=["GET"])
def get_progress(scenario_id):
    progress = save_manager.get_progress(scenario_id)
    if progress is None:
        return jsonify({"error": "No progress found"}), 404
    return jsonify(progress)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
