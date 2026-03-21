import json
import os
from datetime import datetime

from flask import Flask, jsonify, render_template, request

from map_generator import MapGenerator
from save_manager import SaveManager
from sd_generator import request_illustration, get_scene_state, is_sd_enabled, clear_scene, remove_layer
import game_mechanics as gm

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


def restore_scene():
    """Restore web UI scene from current game state. Called on startup and game load."""
    state = load_game_state()
    chapter = state.get("game_info", {}).get("current_chapter", 1)
    events = state.get("events", [])

    # Determine scene name from latest context
    scene_name = None
    # Check recent events for location hints
    for e in reversed(events[-10:]):
        msg = (e.get("message", "") + " " + e.get("narrative", "")).lower()
        if any(k in msg for k in ["마을", "village", "집", "home", "cottage"]):
            scene_name = "village"
            break
        elif any(k in msg for k in ["교역", "road", "길", "여행", "travel"]):
            scene_name = "trade_road"
            break
        elif any(k in msg for k in ["시장", "market", "상점"]):
            scene_name = "market"
            break
        elif any(k in msg for k in ["던전", "dungeon", "동굴"]):
            scene_name = "dungeon"
            break
        elif any(k in msg for k in ["숲", "forest", "나무"]):
            scene_name = "forest"
            break
        elif any(k in msg for k in ["보물", "treasure", "황금"]):
            scene_name = "treasure"
            break

    # Fallback to chapter-based scene
    if not scene_name:
        chapter_scenes = {1: "forest", 2: "dungeon", 3: "treasure", 4: "village"}
        scene_name = chapter_scenes.get(chapter, "default")

    # Request illustration (will reuse existing or generate Cairo fallback)
    request_illustration(
        illustration_type="background",
        prompt="",
        turn_count=state.get("turn_count", 0),
        name=scene_name,
    )

    # NPC 레이어는 자동 추가하지 않음 — GM이 나레이션 시 명시적으로 추가
    # 배경만 복원하고, NPC/오브젝트 레이어는 게임 진행 중 GM이 관리


# Generate initial map and restore scene on startup
update_map_image()
restore_scene()


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
            result = dict(p)
            # Merge entity file data (equipment, available_actions)
            scenario_id = state.get("game_info", {}).get("scenario_id", "")
            entity_path = os.path.join(BASE_DIR, "entities", scenario_id, "players", f"player_{player_id}.json")
            if os.path.exists(entity_path):
                with open(entity_path, "r", encoding="utf-8") as f:
                    entity = json.load(f)
                result.setdefault("equipment", entity.get("equipment"))
                result.setdefault("available_actions", entity.get("available_actions"))
            return jsonify(result)
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

    # 턴 추적기에 gm-update 실행 기록
    gm._log_to_tracker("gm-update", data.get("description", "웹 UI 반영")[:60])

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

    # Add new NPCs if provided + auto-create entity files
    for new_npc in data.get("new_npcs", []):
        state["npcs"].append(new_npc)
        gm.create_npc_entity(new_npc, state)

    state["turn_count"] += 1
    event = {
        "turn": state["turn_count"],
        "message": f"[GM] {description}",
        "narrative": narrative,
        "timestamp": datetime.now().strftime("%H:%M:%S"),
    }
    state["events"].append(event)

    # Process mechanics requests (자동 판정/회복/전투)
    mechanics_results = []
    for mreq in data.get("mechanics", []):
        mtype = mreq.get("type", "")
        if mtype == "long_rest":
            mechanics_results.append(gm.long_rest(state))
        elif mtype == "short_rest":
            mechanics_results.append(gm.short_rest(state))
        elif mtype == "attack":
            mechanics_results.append(gm.attack_roll(
                mreq["attacker"], mreq["target"],
                mreq.get("action", "공격"), state))
        elif mtype == "skill_check":
            mechanics_results.append(gm.skill_check(
                mreq["player"], mreq["stat"], mreq["dc"], state))
        elif mtype == "damage":
            mechanics_results.append(gm.apply_damage(
                mreq["target"], mreq["amount"],
                mreq.get("source", ""), state))
        elif mtype == "heal":
            mechanics_results.append(gm.cast_heal(
                mreq["caster"], mreq["target"], state))
        elif mtype == "use_item":
            mechanics_results.append(gm.use_item(
                mreq["player"], mreq["item"], state))
        elif mtype == "tick_status":
            mechanics_results.append(gm.tick_status_effects(state))
        elif mtype == "grant_xp":
            mechanics_results.append(gm.grant_xp(
                mreq["player"], mreq["amount"],
                mreq.get("source", ""), state))
        elif mtype == "grant_xp_party":
            mechanics_results.append(gm.grant_xp_party(
                mreq["amount"], mreq.get("source", ""), state))
        elif mtype == "allocate_stats":
            mechanics_results.append(gm.allocate_stats(
                mreq["player"], mreq["stats"], state))

    # Update game status if provided
    if "game_status" in data:
        state["game_info"]["status"] = data["game_status"]

    save_game_state(state)
    gm.sync_all_players(state)
    gm._log_to_tracker("state", "game_state 저장 + 엔티티 동기화")
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

    return jsonify({"success": True, "event": event, "turn": state["turn_count"],
                     "illustration": ill_result, "mechanics": mechanics_results})


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
        4: {"sd": "/static/illustrations/sd/background_village_night.webp", "pixel": "/static/illustrations/pixel/forest.png"},
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


@app.route("/api/rules", methods=["GET"])
def get_rules():
    rules_path = os.path.join(BASE_DIR, "rules.json")
    with open(rules_path, "r", encoding="utf-8") as f:
        rules = json.load(f)
    return jsonify(rules)


@app.route("/api/scenario", methods=["GET"])
def get_scenario():
    scenario_path = os.path.join(BASE_DIR, "scenario.json")
    with open(scenario_path, "r", encoding="utf-8") as f:
        scenario = json.load(f)
    return jsonify(scenario)


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
    restore_scene()
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
