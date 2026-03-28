import json
import os
import sys
sys.stdout.reconfigure(encoding='utf-8')
from datetime import datetime

from flask import Flask, jsonify, render_template, request

from core.map_generator import MapGenerator
from core.save_manager import SaveManager, archive_old_events
from core.sd_generator import request_illustration, get_scene_state, set_scene_state, is_sd_enabled, clear_scene, remove_layer
import core.game_mechanics as gm
from core.worldbuilding_agent import check_and_warn as wb_check
from core.rules_agent import check_and_warn as rules_check
from core.scenario_agent import check_and_warn as scenario_check
from core.npc_agent import check_and_warn as npc_check
from core.worldmap_agent import check_and_warn as worldmap_check

import time
import signal
import threading
import subprocess as _subprocess

# ─── 유휴 자동 종료 ───
_last_state_change = time.time()
_shutdown_armed = False
_idle_timer = None
_IDLE_TIMEOUT = 180  # 3분

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GAME_STATE_PATH = os.path.join(BASE_DIR, "data", "game_state.json")


_ko_cache = None
def _get_ko_name(en_name):
    """ko.json에서 영어→한국어 이름 변환."""
    global _ko_cache
    if _ko_cache is None:
        ko_path = os.path.join(BASE_DIR, "lang", "ko.json")
        try:
            with open(ko_path, "r", encoding="utf-8") as f:
                _ko_cache = json.load(f)
        except Exception:
            _ko_cache = {}
    return _ko_cache.get("npcs", {}).get(en_name, "") or _ko_cache.get("creatures", {}).get(en_name, "")


def _add_npc_layers(state):
    """현재 위치의 NPC를 일러스트 레이어에 자동 추가."""
    player1 = next((p for p in state.get("players", []) if p.get("id") == 1), None)
    if not player1:
        return
    p1_x = player1["position"][0]
    p1_y = player1["position"][1]
    current_loc = state.get("current_location", "")

    # 기존 NPC portrait 레이어 제거 (위치 재계산을 위해)
    scene = get_scene_state()
    for layer in list(scene.get("layers", [])):
        if layer.get("type") == "portrait":
            remove_layer(layer.get("name", ""))

    npcs_to_add = []
    for npc in state.get("npcs", []):
        if npc.get("status") not in ("alive", "idle", "active"):
            continue
        npc_loc = npc.get("location", "")
        if current_loc and npc_loc and npc_loc != current_loc:
            continue
        npc_name = npc.get("name", "")
        # ko.json에서 한국어 이름 조회 (portrait 파일이 한국어일 수 있음)
        ko_name = _get_ko_name(npc_name)
        # Portrait exists check — 영어 이름 + 한국어 이름 모두 시도
        portrait_exists = False
        portrait_path = ""
        for try_name in [npc_name, ko_name]:
            if not try_name:
                continue
            for ext in [".webp", ".png"]:
                for prefix in ["portrait_", ""]:
                    candidate = os.path.join(BASE_DIR, "static", "portraits", "sd", f"{prefix}{try_name}{ext}")
                    if os.path.exists(candidate):
                        portrait_exists = True
                        portrait_path = candidate
                        break
                if portrait_exists:
                    break
            if portrait_exists:
                break
        if not portrait_exists:
            continue
        # Distance and position
        npc_pos = npc.get("position", [0, 0])
        sort_key = -(npc_pos[0] - p1_x)
        distance = max(abs(npc_pos[0] - p1_x), abs(npc_pos[1] - p1_y))
        if distance <= 1:
            size_class = "d1"
        elif distance <= 2:
            size_class = "d2"
        elif distance <= 4:
            size_class = "d3"
        else:
            size_class = "d4"
        npcs_to_add.append((sort_key, npc_name, distance, size_class, portrait_path))

    npcs_to_add.sort(key=lambda x: x[0])
    for idx, (sort_key, npc_name, distance, size_class, portrait_path) in enumerate(npcs_to_add[:4]):
        # Map relative dx to screen position name
        # sort_key = -(npc_x - p1_x), mirrored: positive sort_key = right on screen
        if sort_key > 1:
            pos_name = "far-right"
        elif sort_key == 1:
            pos_name = "right"
        elif sort_key == 0:
            pos_name = "center"
        elif sort_key == -1:
            pos_name = "left"
        else:
            pos_name = "far-left"

        request_illustration(
            illustration_type="portrait",
            prompt="",
            turn_count=state.get("turn_count", 0),
            position=pos_name,
            name=npc_name,
            distance=distance,
            size_class=size_class,
        )


def load_game_state():
    try:
        with open(GAME_STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        return {"error": str(e), "players": [], "npcs": [], "map": {}, "events": [], "current_scene": {}}


save_manager = SaveManager()


def save_game_state(state):
    with open(GAME_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    # 이벤트 아카이빙: max_recent 초과 시 오래된 이벤트를 아카이브 파일로 이동
    archive_old_events(GAME_STATE_PATH)
    # 아카이빙 후 최신 state를 다시 읽어서 이후 save_game에 반영
    with open(GAME_STATE_PATH, "r", encoding="utf-8") as f:
        state = json.load(f)
    # 자동 저장: 시나리오 ID 기반으로 슬롯 1에 항상 저장
    scenario_id = state.get("game_info", {}).get("scenario_id", "default")
    turn = state.get("turn_count", 0)
    save_manager.save_game(scenario_id, slot=1, description=f"자동 저장 (턴 {turn})")


def _save_scene_to_state(state):
    """현재 scene_state를 game_state에 저장"""
    scene = get_scene_state()
    state["current_scene"] = {
        "background": scene.get("background"),
        "layers": scene.get("layers", []),
    }


def update_map_image():
    gen = MapGenerator()
    gen.save_map()


def _find_best_background(state):
    """현재 위치/시간대에 맞는 최적 배경 일러스트를 찾는다.
    매칭 실패 시 None 반환 (기존 배경 유지)."""
    import glob as _glob

    ill_dir = os.path.join(BASE_DIR, "static", "illustrations", "sd")
    if not os.path.isdir(ill_dir):
        return None

    # 사용 가능한 배경 파일 목록
    bg_files = []
    for ext in ("*.webp", "*.png"):
        bg_files.extend(_glob.glob(os.path.join(ill_dir, f"background_{ext}")))
    if not bg_files:
        return None

    # 파일명만 추출 (경로 제외)
    bg_names = {os.path.basename(f): f"/static/illustrations/sd/{os.path.basename(f)}" for f in bg_files}

    location = state.get("current_location", "")
    # location 키워드 추출: "trade_road_karendel" → ["trade", "road", "karendel"]
    loc_keywords = [k.lower() for k in location.replace("-", "_").split("_") if len(k) > 2]

    # 시간대 감지: 최근 나레이션에서 밤/낮 키워드
    night_keywords = ["밤", "야영", "night", "새벽", "dawn", "모닥불", "달빛", "어둠"]
    is_night = False
    events = state.get("events", [])
    for ev in reversed(events[-5:]):  # 최근 5개 이벤트만
        narr = (ev.get("narrative", "") + ev.get("message", "")).lower()
        if any(kw in narr for kw in night_keywords):
            is_night = True
            break

    # 1순위: worldbuilding.json의 default_bg
    try:
        wb_path = os.path.join(BASE_DIR, "data", "worldbuilding.json")
        with open(wb_path, "r", encoding="utf-8") as f:
            wb = json.load(f)
        loc_data = wb.get("locations", {}).get(location, {})
        default_bg = loc_data.get("default_bg", {})
        if default_bg:
            time_key = "night" if is_night else "day"
            bg_url = default_bg.get(time_key)
            if bg_url:
                bg_file = os.path.join(BASE_DIR, bg_url.lstrip("/"))
                if os.path.isfile(bg_file):
                    return bg_url
            # 시간대 매칭 실패 시 반대 시간대도 시도
            alt_key = "day" if is_night else "night"
            bg_url_alt = default_bg.get(alt_key)
            if bg_url_alt:
                bg_file_alt = os.path.join(BASE_DIR, bg_url_alt.lstrip("/"))
                if os.path.isfile(bg_file_alt):
                    return bg_url_alt
    except Exception:
        pass

    # 2순위: 파일명 키워드 매칭 (기존 로직)
    best_score = 0
    best_bg = None
    for fname, url in bg_names.items():
        fname_lower = fname.lower()
        score = 0
        for kw in loc_keywords:
            if kw in fname_lower:
                score += 1
        # 시간대 보너스
        if is_night and "night" in fname_lower:
            score += 2
        elif not is_night and "night" not in fname_lower and score > 0:
            score += 1

        if score > best_score:
            best_score = score
            best_bg = url

    # 최소 1개 키워드 매칭 필요
    return best_bg if best_score >= 1 else None


def restore_scene():
    """Restore web UI scene from current game state. Called on startup and game load."""
    state = load_game_state()
    saved_scene = state.get("current_scene")

    if saved_scene and saved_scene.get("background"):
        background = saved_scene["background"]

        # 배경 파일 존재 여부 + 위치 적합성 검증
        bg_path = os.path.join(BASE_DIR, background.lstrip("/")) if background else None
        needs_fix = False
        if bg_path and not os.path.isfile(bg_path):
            needs_fix = True  # 파일 자체가 없음

        # 위치 키워드가 배경 파일명에 없으면 불일치 가능
        if not needs_fix:
            location = state.get("current_location", "")
            loc_keywords = [k.lower() for k in location.replace("-", "_").split("_") if len(k) > 2]
            bg_basename = os.path.basename(background).lower()
            # ch1_forest.png 같은 챕터 기본 배경이면 항상 재검증
            if bg_basename.startswith("ch") and "_" in bg_basename:
                needs_fix = True
            # location 키워드가 하나도 안 맞고, 턴이 있으면 (초기 상태가 아니면) 재검증
            elif loc_keywords and not any(kw in bg_basename for kw in loc_keywords):
                if state.get("turn_count", 0) > 0:
                    needs_fix = True

        if needs_fix:
            better_bg = _find_best_background(state)
            if better_bg:
                background = better_bg

        set_scene_state(
            background=background,
            layers=saved_scene.get("layers", [])
        )
        _add_npc_layers(state)
    else:
        # current_scene이 없으면 기존 폴백: 챕터 기반
        chapter = state.get("game_info", {}).get("current_chapter", 1)
        chapter_scenes = {1: "forest", 2: "dungeon", 3: "treasure", 4: "village"}
        scene_name = chapter_scenes.get(chapter, "default")
        request_illustration(
            illustration_type="background",
            prompt="",
            turn_count=state.get("turn_count", 0),
            name=scene_name,
        )
        _add_npc_layers(state)

    # docs/ 동기화
    try:
        save_manager._sync_docs(state)
    except Exception:
        pass


def _startup_init():
    """서버 시작 시 초기화 — import만으로는 실행되지 않음."""
    # Generate world map on startup (4단계 파이프라인)
    try:
        from core.world_map import generate_world_map_pipeline
        generate_world_map_pipeline()
    except Exception:
        pass

    # Generate initial map and restore scene on startup
    update_map_image()
    restore_scene()

    # 초상화 배경 자동 제거 (투명 아닌 초상화 수정)
    try:
        from core.sd_generator import remove_all_portrait_backgrounds
        bg_result = remove_all_portrait_backgrounds()
        if bg_result["processed"] > 0:
            print(f"  [OK] 초상화 배경 제거: {bg_result['processed']}장")
    except Exception:
        pass


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/game-state", methods=["GET"])
def get_game_state():
    state = load_game_state()
    # objects 로드 (entities/{scenario_id}/objects/)
    objects = []
    scenario_id = state.get("game_info", {}).get("scenario_id", "")
    if scenario_id:
        obj_dir = os.path.join(BASE_DIR, "entities", scenario_id, "objects")
        if os.path.isdir(obj_dir):
            for fname in sorted(os.listdir(obj_dir)):
                if fname.endswith(".json"):
                    try:
                        with open(os.path.join(obj_dir, fname), "r", encoding="utf-8") as f:
                            objects.append(json.load(f))
                    except Exception:
                        pass
    state["objects"] = objects
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
        "narrative": "",
        "user_input": action,
        "dialogues": [],
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

    # 저장 후 활동 감지 → 타이머 해제 (다음 저장까지 서버 유지)
    global _shutdown_armed, _idle_timer
    if _shutdown_armed:
        _shutdown_armed = False
        if _idle_timer:
            _idle_timer.cancel()
            _idle_timer = None

    state = load_game_state()

    # 턴 추적기에 gm-update 실행 기록
    gm._log_to_tracker("gm-update", data.get("description", "웹 UI 반영")[:60])

    description = data.get("description", "")
    narrative = data.get("narrative", "")

    mechanics_results = []

    # Apply player updates
    for pu in data.get("player_updates", []):
        for p in state["players"]:
            if p["id"] == pu["id"]:
                for key, val in pu.items():
                    if key != "id":
                        if key == "position" and isinstance(val, list):
                            p["position"] = val
                            # 위험 타일 체크
                            from core.game_mechanics import check_hazard_tile
                            hazard = check_hazard_tile(p["id"], val, state)
                            if hazard.get("hazard"):
                                mechanics_results.append(hazard)
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
                            # 위험 타일 체크
                            from core.game_mechanics import check_hazard_tile
                            hazard = check_hazard_tile(n["id"], val, state)
                            if hazard.get("hazard"):
                                mechanics_results.append(hazard)
                        elif key == "status":
                            n["status"] = val
                        elif key == "known":
                            n["known"] = bool(val)
                break

    # Add new NPCs if provided + auto-create entity files
    for new_npc in data.get("new_npcs", []):
        state["npcs"].append(new_npc)
        gm.create_npc_entity(new_npc, state)

    # turn_count 증가는 GM이 직접 관리 — API에서 자동 증가하지 않음
    # 단, turn이 명시적으로 제공된 경우 해당 값으로 설정
    if "turn" in data:
        state["turn_count"] = data["turn"]

    # 이벤트는 description 또는 narrative가 있을 때만 추가
    event = None
    if description or narrative:
        event = {
            "turn": state["turn_count"],
            "message": f"[GM] {description}" if description else "",
            "narrative": narrative,
            "user_input": data.get("user_input", ""),
            "dialogues": data.get("dialogues", []),
            "timestamp": datetime.now().strftime("%H:%M:%S"),
        }
        # 판정 상세 기록 — show_dice_result와 무관하게 항상 기록
        if data.get("dice_rolls"):
            event["dice_rolls"] = data["dice_rolls"]
        state["events"].append(event)

    # Process mechanics requests (자동 판정/회복/전투)
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
        elif mtype == "turn_start":
            mechanics_results.append(gm.turn_start_check(state))
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

    # mechanics 결과를 이벤트에 자동 기록 (판정 상세 영구 보존)
    if mechanics_results and event:
        event["mechanics_results"] = mechanics_results
    elif mechanics_results and not event:
        # 나레이션 없이 mechanics만 호출된 경우에도 기록
        mech_event = {
            "turn": state["turn_count"],
            "message": "[시스템] 판정 처리",
            "mechanics_results": mechanics_results,
            "timestamp": datetime.now().strftime("%H:%M:%S"),
        }
        state["events"].append(mech_event)

    # Update game status if provided
    if "game_status" in data:
        state["game_info"]["status"] = data["game_status"]

    # Update location if provided — 맵 + 배경 자동 교체
    if "location" in data:
        new_loc = data["location"]
        old_loc = state.get("current_location", "")
        if new_loc != old_loc:
            state["current_location"] = new_loc
            # worldbuilding에서 새 location의 맵 데이터 로드
            try:
                wb_path = os.path.join(BASE_DIR, "data", "worldbuilding.json")
                with open(wb_path, "r", encoding="utf-8") as f:
                    wb = json.load(f)
                loc_data = wb.get("locations", {}).get(new_loc, {})
                if loc_data.get("map"):
                    state["map"] = {
                        "width": loc_data["map"]["width"],
                        "height": loc_data["map"]["height"],
                        "tile_size": state.get("map", {}).get("tile_size", 40),
                        "locations": loc_data["map"]["areas"],
                    }
            except Exception:
                pass

    # Handle scene management commands (clear BEFORE illustration to avoid wiping new background)
    if data.get("clear_scene"):
        clear_scene()
    if data.get("remove_layer"):
        remove_layer(data["remove_layer"])

    # Handle illustration request (재활용 체크 우선 — 즉시 적용)
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

    # Entity overlap prevention — auto-relocate after position updates
    try:
        all_positions = {}
        # Collect all current positions
        for p in state.get("players", []):
            pos_key = tuple(p.get("position", [0, 0]))
            if pos_key in all_positions:
                # Overlap detected - find nearest empty
                alt = gm._find_nearest_empty(list(pos_key), p["id"], state)
                if alt:
                    p["position"] = alt
            else:
                all_positions[pos_key] = p.get("name", f"player_{p['id']}")

        for n in state.get("npcs", []):
            if n.get("status") in ("dead", "fled", "gone"):
                continue
            pos_key = tuple(n.get("position", [0, 0]))
            if pos_key in all_positions:
                alt = gm._find_nearest_empty(list(pos_key), n["id"], state)
                if alt:
                    n["position"] = alt
            else:
                all_positions[pos_key] = n.get("name", f"npc_{n['id']}")
    except Exception:
        pass  # Don't block gm-update on overlap check failure

    # scene_state를 game_state에 저장
    _save_scene_to_state(state)

    save_game_state(state)
    gm.sync_all_players(state)
    gm._log_to_tracker("state", "game_state 저장 + 엔티티 동기화")
    update_map_image()

    # docs/ 동기화 (GitHub Pages용)
    try:
        save_manager._sync_docs(state)
    except Exception:
        pass

    # 월드맵 갱신 (세계관 변경 반영 — 파이프라인)
    try:
        from core.world_map import generate_world_map_pipeline
        generate_world_map_pipeline()
    except Exception:
        pass

    _add_npc_layers(state)

    # ─── 에이전트 자동 검증 (Agent 호출 후의 최종 상태를 체크하는 안전망) ───
    agent_warnings = {}

    wb_w = wb_check(narrative=f"{description} {narrative}", game_state=state)
    if wb_w:
        gm._log_to_tracker("agent:worldbuilding", f"⚠ 미등록 {len(wb_w)}건 감지")
        agent_warnings["worldbuilding"] = wb_w
    else:
        gm._log_to_tracker("agent:worldbuilding", "세계관 정합성 확인")

    rules_w = rules_check(game_state=state, mechanics_results=mechanics_results)
    if rules_w:
        gm._log_to_tracker("agent:rules", f"⚠ 룰 위반 {len(rules_w)}건 감지")
        agent_warnings["rules"] = rules_w
    else:
        gm._log_to_tracker("agent:rules", "룰 정합성 확인")

    scenario_w = scenario_check(game_state=state)
    if scenario_w:
        gm._log_to_tracker("agent:scenario", f"📜 시나리오 감지 {len(scenario_w)}건")
        agent_warnings["scenario"] = scenario_w
    else:
        gm._log_to_tracker("agent:scenario", "시나리오 정합성 확인")

    npc_w = npc_check(game_state=state)
    if npc_w:
        gm._log_to_tracker("agent:npc", f"⚠ NPC 문제 {len(npc_w)}건 감지")
        agent_warnings["npc"] = npc_w
    else:
        gm._log_to_tracker("agent:npc", "NPC 정합성 확인")

    worldmap_w = worldmap_check(game_state=state)
    if worldmap_w:
        gm._log_to_tracker("agent:worldmap", f"🗺️ 세계지도 문제 {len(worldmap_w)}건 감지")
        agent_warnings["worldmap"] = worldmap_w
    else:
        gm._log_to_tracker("agent:worldmap", "세계 지도 정합성 확인")

    return jsonify({"success": True, "event": event or {}, "turn": state["turn_count"],
                     "illustration": ill_result, "mechanics": mechanics_results,
                     "agent_warnings": agent_warnings})


@app.route("/api/world-map", methods=["POST"])
def regenerate_world_map():
    try:
        from core.world_map import generate_world_map_pipeline
        path = generate_world_map_pipeline()
        if path:
            # 경로에서 static/ 이하 상대경로 추출
            rel = path.replace("\\", "/")
            idx = rel.find("static/")
            web_path = "/" + rel[idx:] if idx >= 0 else "/static/maps/world/world_map.png"
            return jsonify({"success": True, "path": web_path})
        return jsonify({"success": False, "reason": "No locations with world_pos"})
    except Exception as e:
        return jsonify({"success": False, "reason": str(e)})


@app.route("/api/world-map/regenerate", methods=["POST"])
def regenerate_world_map_full():
    """전체 파이프라인 강제 재실행 (모든 캐시 무시)."""
    try:
        from core.world_map import generate_world_map_pipeline
        path = generate_world_map_pipeline(force_regenerate=True)
        if path:
            rel = path.replace("\\", "/")
            idx = rel.find("static/")
            web_path = "/" + rel[idx:] if idx >= 0 else "/static/maps/world/world_map.png"
            return jsonify({"success": True, "path": web_path})
        return jsonify({"success": False, "reason": "No locations with world_pos"})
    except Exception as e:
        return jsonify({"success": False, "reason": str(e)})


@app.route("/api/portraits/fix-backgrounds", methods=["POST"])
def fix_portrait_backgrounds():
    try:
        from core.sd_generator import remove_all_portrait_backgrounds
        results = remove_all_portrait_backgrounds()
        return jsonify({"success": True, **results})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


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
        "show_system_log": session.get("show_system_log", False),
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
    if "show_system_log" in data:
        session["show_system_log"] = bool(data["show_system_log"])
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


@app.route("/api/worldbuilding", methods=["GET"])
def get_worldbuilding():
    wb_path = os.path.join(BASE_DIR, "data", "worldbuilding.json")
    try:
        with open(wb_path, "r", encoding="utf-8") as f:
            wb = json.load(f)
        return jsonify(wb)
    except FileNotFoundError:
        return jsonify({"error": "파일 없음"}), 404
    except json.JSONDecodeError:
        return jsonify({"error": "JSON 파싱 실패"}), 500


@app.route("/api/ko", methods=["GET"])
def get_ko():
    ko_path = os.path.join(BASE_DIR, "lang", "ko.json")
    try:
        with open(ko_path, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    except FileNotFoundError:
        return jsonify({"error": "ko.json not found"}), 404


@app.route("/api/items", methods=["GET"])
def get_items():
    items_path = os.path.join(BASE_DIR, "data", "items.json")
    try:
        with open(items_path, "r", encoding="utf-8") as f:
            items = json.load(f)
        return jsonify(items)
    except FileNotFoundError:
        return jsonify({"error": "파일 없음"}), 404
    except json.JSONDecodeError:
        return jsonify({"error": "JSON 파싱 실패"}), 500


@app.route("/api/skills", methods=["GET"])
def get_skills():
    skills_path = os.path.join(BASE_DIR, "data", "skills.json")
    try:
        with open(skills_path, "r", encoding="utf-8") as f:
            skills = json.load(f)
        return jsonify(skills)
    except FileNotFoundError:
        return jsonify({"error": "파일 없음"}), 404
    except json.JSONDecodeError:
        return jsonify({"error": "JSON 파싱 실패"}), 500


@app.route("/api/rules", methods=["GET"])
def get_rules():
    rules_path = os.path.join(BASE_DIR, "data", "rules.json")
    try:
        with open(rules_path, "r", encoding="utf-8") as f:
            rules = json.load(f)
        return jsonify(rules)
    except FileNotFoundError:
        return jsonify({"error": "파일 없음"}), 404
    except json.JSONDecodeError:
        return jsonify({"error": "JSON 파싱 실패"}), 500


@app.route("/api/scenario", methods=["GET"])
def get_scenario():
    scenario_path = os.path.join(BASE_DIR, "data", "scenario.json")
    try:
        with open(scenario_path, "r", encoding="utf-8") as f:
            scenario = json.load(f)
        return jsonify(scenario)
    except FileNotFoundError:
        return jsonify({"error": "파일 없음"}), 404
    except json.JSONDecodeError:
        return jsonify({"error": "JSON 파싱 실패"}), 500


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
                "narrative": "",
                "user_input": "",
                "dialogues": [],
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


@app.route("/api/save", methods=["POST"])
def explicit_save():
    """유저 명시적 저장 요청. 저장 후 유휴 타이머 시작."""
    data = request.get_json() or {}
    state = load_game_state()
    scenario_id = state.get("game_info", {}).get("scenario_id", "default")
    slot = data.get("slot", 1)
    description = data.get("description", "")

    result = save_manager.save_game(scenario_id, slot=slot, description=description)
    if result is None:
        return jsonify({"success": False, "message": "저장 실패"}), 400

    # 명시적 저장 → 유휴 타이머 시작
    global _shutdown_armed
    _shutdown_armed = True
    _start_idle_timer()
    print(f"[AUTO] 유휴 자동 종료 타이머 시작 ({_IDLE_TIMEOUT}초)")

    return jsonify({"success": True, "save_info": result})


@app.route("/api/progress/<scenario_id>", methods=["GET"])
def get_progress(scenario_id):
    progress = save_manager.get_progress(scenario_id)
    if progress is None:
        return jsonify({"error": "No progress found"}), 404
    return jsonify(progress)


@app.route("/api/status-effects", methods=["GET"])
def get_status_effects():
    path = os.path.join(BASE_DIR, "data", "status_effects.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    except FileNotFoundError:
        return jsonify({"error": "파일 없음"}), 404
    except json.JSONDecodeError:
        return jsonify({"error": "JSON 파싱 실패"}), 500


@app.route("/api/creatures", methods=["GET"])
def get_creatures():
    path = os.path.join(BASE_DIR, "data", "creature_templates.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    except FileNotFoundError:
        return jsonify({"error": "파일 없음"}), 404
    except json.JSONDecodeError:
        return jsonify({"error": "JSON 파싱 실패"}), 500


@app.route("/api/shops", methods=["GET"])
def get_shops():
    path = os.path.join(BASE_DIR, "data", "shops.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    except FileNotFoundError:
        return jsonify({"error": "파일 없음"}), 404
    except json.JSONDecodeError:
        return jsonify({"error": "JSON 파싱 실패"}), 500


@app.route("/api/quests", methods=["GET"])
def get_quests():
    path = os.path.join(BASE_DIR, "data", "quests.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    except FileNotFoundError:
        return jsonify({"error": "파일 없음"}), 404
    except json.JSONDecodeError:
        return jsonify({"error": "JSON 파싱 실패"}), 500


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


@app.route("/api/idle-shutdown/disarm", methods=["POST"])
def disarm_idle_shutdown():
    """유휴 자동 종료 타이머 해제."""
    global _shutdown_armed, _idle_timer
    _shutdown_armed = False
    if _idle_timer:
        _idle_timer.cancel()
        _idle_timer = None
    return jsonify({"success": True, "message": "유휴 자동 종료 해제됨"})


# ─── 유휴 자동 종료 시스템 ───

def _start_idle_timer():
    """저장 후 유휴 타이머 시작/리셋."""
    global _idle_timer
    if _idle_timer:
        _idle_timer.cancel()
    _idle_timer = threading.Timer(_IDLE_TIMEOUT, _check_and_shutdown)
    _idle_timer.daemon = True
    _idle_timer.start()


def _check_and_shutdown():
    """타이머 만료 시 서버 종료."""
    if not _shutdown_armed:
        return

    print(f"\n[AUTO] {_IDLE_TIMEOUT}초간 게임 상태 변경 없음 — 서버 자동 종료")

    # SD WebUI 종료 (포트 7860)
    _kill_port_process(7860)

    # Flask 자신 종료
    os._exit(0)


def _kill_port_process(port):
    """지정 포트의 LISTEN 프로세스를 종료 (Windows)."""
    try:
        result = _subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            if f":{port} " in line and "LISTEN" in line:
                parts = line.strip().split()
                pid = parts[-1]
                try:
                    pid_int = int(pid)
                    if pid_int > 0 and pid_int != os.getpid():
                        _subprocess.run(["taskkill", "/F", "/PID", pid], timeout=5)
                        print(f"  [OK] 포트 {port} 프로세스 종료 (PID {pid})")
                except (ValueError, Exception):
                    pass
    except Exception as e:
        print(f"  [WARN] 포트 {port} 프로세스 종료 실패: {e}")


if __name__ == "__main__":
    _startup_init()
    app.run(host="0.0.0.0", port=5000, debug=True)
