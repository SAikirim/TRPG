import json
import os
from datetime import datetime

from flask import Flask, jsonify, render_template, request

from core.map_generator import MapGenerator
from core.save_manager import SaveManager
from core.sd_generator import request_illustration, get_scene_state, is_sd_enabled, clear_scene, remove_layer
import core.game_mechanics as gm

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GAME_STATE_PATH = os.path.join(BASE_DIR, "data", "game_state.json")


def _add_npc_layers(state):
    """현재 위치의 NPC를 일러스트 레이어에 자동 추가."""
    player1 = next((p for p in state.get("players", []) if p.get("id") == 1), None)
    if not player1:
        return
    p1_x = player1["position"][0]
    p1_y = player1["position"][1]
    current_loc = state.get("current_location", "")

    npcs_to_add = []
    for npc in state.get("npcs", []):
        if npc.get("status") not in ("alive", "idle", "active"):
            continue
        npc_loc = npc.get("location", "")
        if current_loc and npc_loc and npc_loc != current_loc:
            continue
        npc_name = npc.get("name", "")
        # Portrait exists check
        portrait_exists = False
        for ext in [".webp", ".png"]:
            for prefix in ["portrait_", ""]:
                if os.path.exists(os.path.join(BASE_DIR, "static", "portraits", "sd", f"{prefix}{npc_name}{ext}")):
                    portrait_exists = True
                    break
            if portrait_exists:
                break
        if not portrait_exists:
            continue
        # Already in layers check
        scene = get_scene_state()
        if any(l.get("name") == npc_name for l in scene.get("layers", [])):
            continue
        # Distance and position
        npc_pos = npc.get("position", [0, 0])
        sort_key = -(npc_pos[0] - p1_x)
        distance = abs(npc_pos[0] - p1_x) + abs(npc_pos[1] - p1_y)
        if distance <= 1:
            size_class = "near"
        elif distance <= 2:
            size_class = "close"
        elif distance <= 4:
            size_class = "medium"
        else:
            size_class = "far"
        npcs_to_add.append((sort_key, npc_name, distance, size_class))

    npcs_to_add.sort(key=lambda x: x[0])
    for idx, (_, npc_name, distance, size_class) in enumerate(npcs_to_add):
        if idx > 3:
            break
        request_illustration(
            illustration_type="portrait",
            prompt="",
            turn_count=state.get("turn_count", 0),
            position=str(idx),
            name=npc_name,
            distance=distance,
            size_class=size_class,
        )


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

    _add_npc_layers(state)

    # docs/ 동기화 (정적 웹 반영)
    try:
        save_manager._sync_docs(state)
    except Exception:
        pass


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
                        elif key == "known":
                            n["known"] = bool(val)
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

    _add_npc_layers(state)

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
    session_path = os.path.join(BASE_DIR, "data", "current_session.json")
    with open(session_path, "r", encoding="utf-8") as f:
        session = json.load(f)
    current = session.get("sd_illustration", False)
    session["sd_illustration"] = not current
    with open(session_path, "w", encoding="utf-8") as f:
        json.dump(session, f, ensure_ascii=False, indent=2)
    return jsonify({"sd_illustration": session["sd_illustration"]})


@app.route("/api/settings", methods=["GET"])
def get_settings():
    session_path = os.path.join(BASE_DIR, "data", "current_session.json")
    with open(session_path, "r", encoding="utf-8") as f:
        session = json.load(f)
    state = load_game_state()
    return jsonify({
        "sd_illustration": session.get("sd_illustration", False),
        "show_dice_result": session.get("show_dice_result", False),
        "display_mode": session.get("display_mode", "mobile"),
        "difficulty": state.get("game_info", {}).get("difficulty", "normal"),
    })


@app.route("/api/settings", methods=["POST"])
def update_settings():
    data = request.get_json()
    session_path = os.path.join(BASE_DIR, "data", "current_session.json")
    with open(session_path, "r", encoding="utf-8") as f:
        session = json.load(f)

    if "sd_illustration" in data:
        session["sd_illustration"] = bool(data["sd_illustration"])
    if "show_dice_result" in data:
        session["show_dice_result"] = bool(data["show_dice_result"])
    if "display_mode" in data and data["display_mode"] in ("mobile", "terminal"):
        session["display_mode"] = data["display_mode"]

    with open(session_path, "w", encoding="utf-8") as f:
        json.dump(session, f, ensure_ascii=False, indent=2)

    # 난이도는 game_state에 저장
    if "difficulty" in data and data["difficulty"] in ("easy", "normal", "hard", "nightmare"):
        state = load_game_state()
        state["game_info"]["difficulty"] = data["difficulty"]
        # stat_pool 연동
        pools = {"easy": 55, "normal": 50, "hard": 45, "nightmare": 40}
        state["game_info"]["stat_pool"] = pools.get(data["difficulty"], 50)
        save_game_state(state)

    return jsonify({"success": True})


@app.route("/api/items", methods=["GET"])
def get_items():
    items_path = os.path.join(BASE_DIR, "data", "items.json")
    with open(items_path, "r", encoding="utf-8") as f:
        items = json.load(f)
    return jsonify(items)


@app.route("/api/skills", methods=["GET"])
def get_skills():
    skills_path = os.path.join(BASE_DIR, "data", "skills.json")
    with open(skills_path, "r", encoding="utf-8") as f:
        skills = json.load(f)
    return jsonify(skills)


@app.route("/api/rules", methods=["GET"])
def get_rules():
    rules_path = os.path.join(BASE_DIR, "data", "rules.json")
    with open(rules_path, "r", encoding="utf-8") as f:
        rules = json.load(f)
    return jsonify(rules)


@app.route("/api/scenario", methods=["GET"])
def get_scenario():
    scenario_path = os.path.join(BASE_DIR, "data", "scenario.json")
    with open(scenario_path, "r", encoding="utf-8") as f:
        scenario = json.load(f)
    return jsonify(scenario)


@app.route("/api/reset-game", methods=["POST"])
def reset_game():
    initial_path = os.path.join(BASE_DIR, "data", "game_state_initial.json")
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


@app.route("/api/status-effects", methods=["GET"])
def get_status_effects():
    path = os.path.join(BASE_DIR, "data", "status_effects.json")
    with open(path, "r", encoding="utf-8") as f:
        return jsonify(json.load(f))


@app.route("/api/creatures", methods=["GET"])
def get_creatures():
    path = os.path.join(BASE_DIR, "data", "creature_templates.json")
    with open(path, "r", encoding="utf-8") as f:
        return jsonify(json.load(f))


@app.route("/api/shops", methods=["GET"])
def get_shops():
    path = os.path.join(BASE_DIR, "data", "shops.json")
    with open(path, "r", encoding="utf-8") as f:
        return jsonify(json.load(f))


@app.route("/api/quests", methods=["GET"])
def get_quests():
    path = os.path.join(BASE_DIR, "data", "quests.json")
    with open(path, "r", encoding="utf-8") as f:
        return jsonify(json.load(f))


@app.route("/api/npc/reveal", methods=["POST"])
def reveal_npc():
    data = request.get_json()
    npc_id = data.get("npc_id")
    state = load_game_state()
    for npc in state["npcs"]:
        if npc["id"] == npc_id:
            npc["known"] = True
            break
    save_game_state(state)
    update_map_image()
    return jsonify({"success": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
