#!/usr/bin/env python
"""
TRPG 세션 검증 자동화
- 현재 게임 상태의 일관성을 검사하고, 가능한 문제를 자동 수정
- 세션 시작 시 또는 문제 의심 시 실행

사용법:
  python session_validator.py           # 전체 검증
  python session_validator.py --fix     # 검증 + 자동 수정 (기본값)
  python session_validator.py --check   # 검증만 (수정 안 함)
  python session_validator.py --verbose # 상세 출력
"""
import json
import os
import sys
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 결과 카운터
results = {"ok": 0, "warn": 0, "error": 0, "fixed": 0}
messages = []
FIX_MODE = True
VERBOSE = False


def log(level, msg, auto_fixed=False):
    """검증 결과 기록."""
    results[level] += 1
    if auto_fixed:
        results["fixed"] += 1
        msg += " -> [AUTO-FIXED]"
    tag = {"ok": "[OK]", "warn": "[WARN]", "error": "[ERROR]"}[level]
    line = f"  {tag} {msg}"
    messages.append(line)
    if VERBOSE or level != "ok":
        print(line)


def load_json_safe(path):
    """JSON 파일을 안전하게 로드. 실패 시 None 반환."""
    full = path if os.path.isabs(path) else os.path.join(BASE_DIR, path)
    if not os.path.exists(full):
        return None
    try:
        with open(full, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        log("error", f"{path}: JSON 파싱 실패 - {e}")
        return None


def save_json(path, data):
    full = path if os.path.isabs(path) else os.path.join(BASE_DIR, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ─── 검증 항목들 ───

def check_game_state():
    """game_state.json 존재 및 유효성 검사."""
    print("\n[1] game_state.json 검증")
    state = load_json_safe("data/game_state.json")
    if state is None:
        log("error", "game_state.json이 없거나 파싱 불가")
        return None

    # 필수 키 존재 확인
    required_keys = ["game_info", "players", "npcs", "events", "turn_count"]
    for key in required_keys:
        if key not in state:
            log("error", f"game_state.json에 '{key}' 키 누락")
        else:
            log("ok", f"game_state.json.{key} 존재")

    # game_info 필수 필드
    info = state.get("game_info", {})
    for field in ["scenario_id", "title", "status"]:
        if not info.get(field):
            log("warn", f"game_info.{field} 비어있음")

    # 플레이어 수
    players = state.get("players", [])
    if len(players) == 0:
        log("error", "플레이어가 0명")
    else:
        log("ok", f"플레이어 {len(players)}명 존재")

    return state


def check_current_session(state):
    """current_session.json과 game_state 일치 검사."""
    print("\n[2] current_session.json 검증")
    session = load_json_safe("data/current_session.json")
    if session is None:
        log("error", "current_session.json이 없거나 파싱 불가")
        return None

    if state is None:
        return session

    # 시나리오 ID 일치
    state_sid = state.get("game_info", {}).get("scenario_id", "")
    session_sid = session.get("active_scenario", "")
    if state_sid and session_sid and state_sid != session_sid:
        log("error", f"시나리오 ID 불일치: game_state={state_sid}, session={session_sid}")
        if FIX_MODE:
            session["active_scenario"] = state_sid
            save_json("data/current_session.json", session)
            log("warn", f"current_session.active_scenario를 '{state_sid}'로 수정", auto_fixed=True)
    else:
        log("ok", f"시나리오 ID 일치: {state_sid}")

    # 턴 수 일치 (정확히 같지 않아도 됨, 큰 차이만 경고)
    state_turn = state.get("turn_count", 0)
    session_turn = session.get("turn", 0)
    if abs(state_turn - session_turn) > 5:
        log("warn", f"턴 수 큰 차이: game_state={state_turn}, session={session_turn}")

    # 파티 요약 인원 확인
    party_count = len(session.get("party_summary", []))
    player_count = len(state.get("players", []))
    if party_count != player_count:
        log("warn", f"파티 요약 인원 불일치: session={party_count}, game_state={player_count}")

    return session


def check_player_entities(state):
    """플레이어 엔티티 파일 존재 및 스탯 유효성 검사."""
    print("\n[3] 플레이어 엔티티 검증")
    if state is None:
        log("error", "game_state가 없어 검증 불가")
        return

    scenario_id = state.get("game_info", {}).get("scenario_id", "")
    if not scenario_id:
        log("error", "scenario_id가 비어있어 엔티티 경로 확인 불가")
        return

    players = state.get("players", [])
    ent_dir = os.path.join(BASE_DIR, "entities", scenario_id, "players")

    for p in players:
        pid = p["id"]
        ent_path = os.path.join(ent_dir, f"player_{pid}.json")
        if not os.path.exists(ent_path):
            log("error", f"플레이어 엔티티 누락: player_{pid}.json ({p.get('name', '?')})")
            if FIX_MODE:
                _create_player_entity(scenario_id, p)
                log("warn", f"player_{pid}.json 자동 생성", auto_fixed=True)
        else:
            log("ok", f"player_{pid}.json 존재 ({p.get('name', '?')})")

        # 스탯 유효성
        stats = p.get("stats", {})
        required_stats = ["STR", "DEX", "INT", "CON"]
        for stat in required_stats:
            if stat not in stats:
                log("error", f"플레이어 {p.get('name','?')}의 {stat} 스탯 누락")
            elif not isinstance(stats[stat], (int, float)):
                log("error", f"플레이어 {p.get('name','?')}의 {stat} 값이 숫자가 아님: {stats[stat]}")
            elif stats[stat] < 1 or stats[stat] > 30:
                log("warn", f"플레이어 {p.get('name','?')}의 {stat}={stats[stat]} 비정상 범위")

        # HP/MP 유효성
        if p.get("hp", 0) > p.get("max_hp", 0):
            log("warn", f"플레이어 {p.get('name','?')} HP({p['hp']}) > max_hp({p['max_hp']})")
            if FIX_MODE:
                p["hp"] = p["max_hp"]
        if p.get("mp", 0) > p.get("max_mp", 0):
            log("warn", f"플레이어 {p.get('name','?')} MP({p['mp']}) > max_mp({p['max_mp']})")
            if FIX_MODE:
                p["mp"] = p["max_mp"]


def check_npc_entities(state):
    """NPC 엔티티 파일 존재 및 스탯 검사. 누락 시 자동 생성."""
    print("\n[4] NPC 엔티티 검증")
    if state is None:
        log("error", "game_state가 없어 검증 불가")
        return

    scenario_id = state.get("game_info", {}).get("scenario_id", "")
    if not scenario_id:
        return

    npcs = state.get("npcs", [])
    if not npcs:
        log("ok", "NPC 없음 (정상)")
        return

    npc_dir = os.path.join(BASE_DIR, "entities", scenario_id, "npcs")

    for n in npcs:
        nid = n["id"]
        status = n.get("status", "alive")
        ent_path = os.path.join(npc_dir, f"npc_{nid}.json")

        # 죽은/제거된 NPC는 엔티티 없어도 OK
        if status in ("dead", "removed"):
            if os.path.exists(ent_path):
                log("ok", f"npc_{nid}.json 존재 ({n.get('name','?')}, {status})")
            else:
                log("ok", f"npc_{nid}.json 없음 ({n.get('name','?')}, {status} — 정상)")
            continue

        if not os.path.exists(ent_path):
            log("error", f"NPC 엔티티 누락: npc_{nid}.json ({n.get('name', '?')})")
            if FIX_MODE:
                _create_npc_entity(scenario_id, n)
                log("warn", f"npc_{nid}.json 자동 생성", auto_fixed=True)
        else:
            log("ok", f"npc_{nid}.json 존재 ({n.get('name', '?')})")

        # NPC 스탯 검사
        stats = n.get("stats", {})
        if not stats:
            log("warn", f"NPC {n.get('name','?')}의 스탯 비어있음")


def check_scenario_files(state):
    """시나리오/룰셋 파일 존재 검사."""
    print("\n[5] 시나리오/룰셋 파일 검증")
    for fname in ["scenario.json", "rules.json"]:
        path = os.path.join(BASE_DIR, "data", fname)
        if os.path.exists(path):
            data = load_json_safe(os.path.join("data", fname))
            if data:
                log("ok", f"data/{fname} 존재 + 유효")
            # 파싱 실패는 load_json_safe에서 이미 에러 기록
        else:
            log("error", f"data/{fname} 파일 없음")

    # scenario.json이 현재 game_state의 시나리오와 일치하는지 검증 (scenario_id 기준)
    scenario_data = load_json_safe("data/scenario.json")
    if scenario_data and state:
        gs_scenario_id = state.get("game_info", {}).get("scenario_id", "")
        # scenario.json에서 scenario_id 추출 (scenario_info.id 또는 타이틀 기반 매칭)
        sc_info = scenario_data.get("scenario_info", {})
        sc_id = sc_info.get("id", "")
        sc_title = sc_info.get("title", "")

        # scenario_id가 직접 있으면 그걸로, 없으면 index.json에서 타이틀로 매칭
        if not sc_id and gs_scenario_id:
            idx = load_json_safe("scenarios/index.json")
            if idx:
                for s in idx.get("scenarios", []):
                    if s["id"] == gs_scenario_id:
                        sc_id = s["id"]
                        break

        # scenario_id로 비교 (title은 에필로그 등에서 변경될 수 있으므로 비교하지 않음)
        if gs_scenario_id and sc_id and gs_scenario_id != sc_id:
            log("error", f"scenario.json 불일치: scenario_id='{sc_id}' vs game_state='{gs_scenario_id}'")
            if FIX_MODE:
                idx = load_json_safe("scenarios/index.json")
                if idx:
                    for s in idx.get("scenarios", []):
                        if s["id"] == gs_scenario_id:
                            src = os.path.join(BASE_DIR, s.get("scenario_file", f"scenarios/{gs_scenario_id}.json"))
                            if os.path.exists(src):
                                import shutil
                                shutil.copy2(src, os.path.join(BASE_DIR, "data", "scenario.json"))
                                log("warn", f"scenario.json을 '{gs_scenario_id}'로 교체", auto_fixed=True)
                            break
        else:
            log("ok", f"scenario.json 일치: {gs_scenario_id} ('{sc_title}')")

    # scenarios/index.json + 개별 시나리오 파일 존재 검증
    idx = load_json_safe("scenarios/index.json")
    if idx:
        scenarios = idx.get("scenarios", [])
        log("ok", f"scenarios/index.json 존재 ({len(scenarios)}개 시나리오)")

        # 등록된 모든 시나리오의 파일 존재 확인
        for s in scenarios:
            sid = s["id"]
            sf = s.get("scenario_file", f"{sid}.json")
            # scenarios/ 접두사 붙여서 경로 탐색
            sf_path = os.path.join(BASE_DIR, "scenarios", sf) if not sf.startswith("scenarios/") else os.path.join(BASE_DIR, sf)
            if not os.path.exists(sf_path):
                # scenarios/ 없이도 시도
                alt_path = os.path.join(BASE_DIR, sf)
                if os.path.exists(alt_path):
                    sf_path = alt_path
            if os.path.exists(sf_path):
                log("ok", f"시나리오 파일 존재: {sid} -> {sf}")
            else:
                log("error", f"시나리오 파일 누락: {sid} -> {sf} (index.json에 등록되어 있지만 파일 없음)")

            # initial_state 파일 확인
            isf = s.get("initial_state", "")
            if isf:
                isf_path = os.path.join(BASE_DIR, isf)
                if os.path.exists(isf_path):
                    log("ok", f"초기 상태 파일 존재: {sid} -> {isf}")
                else:
                    log("error", f"초기 상태 파일 누락: {sid} -> {isf}")
    else:
        log("error", "scenarios/index.json 없음 또는 파싱 실패")


def check_worldbuilding(state):
    """worldbuilding.json 존재, 현재 위치, 방향/거리 일관성 검증."""
    print("\n[6] worldbuilding.json 검증")
    wb = load_json_safe("data/worldbuilding.json")
    if wb is None:
        log("error", "worldbuilding.json이 없거나 파싱 불가")
        return

    log("ok", "worldbuilding.json 존재 + 유효")

    if state is None:
        return

    # 현재 위치가 worldbuilding에 존재하는지 확인
    current_loc = state.get("current_location", "")
    locations = wb.get("locations", {})
    if current_loc:
        if current_loc in locations:
            log("ok", f"현재 위치 '{current_loc}' worldbuilding에 존재")
        else:
            log("warn", f"현재 위치 '{current_loc}' worldbuilding.locations에 없음")
    else:
        log("warn", "current_location 비어있음")

    # 방향 대칭 검증: A→B 북쪽이면 B→A 남쪽이어야 함
    opposite = {"북쪽": "남쪽", "남쪽": "북쪽", "동쪽": "서쪽", "서쪽": "동쪽",
                "북동쪽": "남서쪽", "남서쪽": "북동쪽", "북서쪽": "남동쪽", "남동쪽": "북서쪽"}
    direction_errors = []
    for loc_id, loc_data in locations.items():
        conns = loc_data.get("connections", {})
        for target_name, conn_info in conns.items():
            direction = conn_info.get("direction", "")
            target_id = None
            for tid, tdata in locations.items():
                if tdata.get("name") == target_name:
                    target_id = tid
                    break
            if not target_id or target_id not in locations:
                continue
            target_conns = locations[target_id].get("connections", {})
            loc_name = loc_data.get("name", loc_id)
            if loc_name in target_conns:
                reverse_dir = target_conns[loc_name].get("direction", "")
                expected_reverse = opposite.get(direction, "")
                if expected_reverse and reverse_dir != expected_reverse:
                    err_msg = f"방향 불일치: {loc_name}→{target_name}={direction}, {target_name}→{loc_name}={reverse_dir} (예상: {expected_reverse})"
                    direction_errors.append(err_msg)
                    if FIX_MODE:
                        target_conns[loc_name]["direction"] = expected_reverse
                        log("error", err_msg, auto_fixed=True)
                    else:
                        log("error", err_msg)

    if not direction_errors:
        log("ok", "세계관 방향 대칭 검증 통과")

    # 거리 대칭 검증
    distance_errors = []
    for loc_id, loc_data in locations.items():
        conns = loc_data.get("connections", {})
        for target_name, conn_info in conns.items():
            dist = conn_info.get("distance", "")
            target_id = None
            for tid, tdata in locations.items():
                if tdata.get("name") == target_name:
                    target_id = tid
                    break
            if not target_id or target_id not in locations:
                continue
            target_conns = locations[target_id].get("connections", {})
            loc_name = loc_data.get("name", loc_id)
            if loc_name in target_conns:
                reverse_dist = target_conns[loc_name].get("distance", "")
                if dist and reverse_dist and dist != reverse_dist:
                    distance_errors.append(f"거리 불일치: {loc_name}↔{target_name} ({dist} vs {reverse_dist})")
                    log("warn", f"거리 불일치: {loc_name}↔{target_name} ({dist} vs {reverse_dist})")

    if not distance_errors:
        log("ok", "세계관 거리 대칭 검증 통과")

    # NPC 위치 일관성
    for npc in state.get("npcs", []):
        npc_loc = npc.get("location", "")
        if npc_loc and npc_loc not in locations:
            log("warn", f"NPC '{npc.get('name','?')}'의 location '{npc_loc}'이 worldbuilding에 없음")

    if FIX_MODE and direction_errors:
        save_json("data/worldbuilding.json", wb)


def check_services():
    """Flask 서버 및 SD WebUI 접속 확인 (선택적)."""
    print("\n[7] 서비스 접속 확인")

    # Flask
    try:
        req = urllib.request.Request("http://localhost:5000/api/game-state", method="GET")
        resp = urllib.request.urlopen(req, timeout=3)
        if resp.status == 200:
            log("ok", "Flask 서버 (localhost:5000) 정상")
        else:
            log("warn", f"Flask 서버 응답 코드: {resp.status}")
    except Exception:
        log("warn", "Flask 서버 (localhost:5000) 접속 불가 — 미실행 상태")

    # SD WebUI
    try:
        req = urllib.request.Request("http://localhost:7860/sdapi/v1/options", method="GET")
        resp = urllib.request.urlopen(req, timeout=3)
        if resp.status == 200:
            log("ok", "SD WebUI (localhost:7860) 정상")
        else:
            log("warn", f"SD WebUI 응답 코드: {resp.status}")
    except Exception:
        log("warn", "SD WebUI (localhost:7860) 접속 불가 — 미실행 또는 Skia 폴백 사용")


def check_illustrations(state):
    """현재 장면의 일러스트 파일 존재 확인."""
    print("\n[8] 일러스트 파일 검증")
    if state is None:
        return

    chapter = state.get("game_info", {}).get("current_chapter", 1)
    ill_dir = os.path.join(BASE_DIR, "static", "illustrations")

    # SD 디렉토리
    sd_dir = os.path.join(ill_dir, "sd")
    pixel_dir = os.path.join(ill_dir, "pixel")

    if os.path.exists(sd_dir):
        sd_files = [f for f in os.listdir(sd_dir) if f.endswith((".png", ".webp", ".jpg"))]
        log("ok", f"SD 일러스트: {len(sd_files)}개 파일")
    else:
        log("warn", "static/illustrations/sd/ 디렉토리 없음")

    if os.path.exists(pixel_dir):
        px_files = [f for f in os.listdir(pixel_dir) if f.endswith((".png", ".webp", ".jpg"))]
        log("ok", f"Pixel 일러스트: {len(px_files)}개 파일")
    else:
        log("warn", "static/illustrations/pixel/ 디렉토리 없음")


def check_entity_directory_structure(state):
    """entities/ 디렉토리 구조 검증."""
    print("\n[9] entities/ 디렉토리 구조 검증")
    if state is None:
        return

    scenario_id = state.get("game_info", {}).get("scenario_id", "")
    if not scenario_id:
        log("warn", "scenario_id 비어있음 — entities/ 검증 스킵")
        return

    ent_base = os.path.join(BASE_DIR, "entities", scenario_id)
    for sub in ["players", "npcs", "objects"]:
        sub_dir = os.path.join(ent_base, sub)
        if os.path.exists(sub_dir):
            files = [f for f in os.listdir(sub_dir) if f.endswith(".json")]
            log("ok", f"entities/{scenario_id}/{sub}/: {len(files)}개 파일")
        else:
            log("warn", f"entities/{scenario_id}/{sub}/ 디렉토리 없음")
            if FIX_MODE:
                os.makedirs(sub_dir, exist_ok=True)
                log("warn", f"entities/{scenario_id}/{sub}/ 자동 생성", auto_fixed=True)


def check_orphan_npcs(state):
    """game_state에 있지만 엔티티가 없는 NPC, 또는 엔티티는 있지만 game_state에 없는 NPC 탐지."""
    print("\n[10] NPC 고아 파일 검증")
    if state is None:
        return

    scenario_id = state.get("game_info", {}).get("scenario_id", "")
    if not scenario_id:
        return

    npc_dir = os.path.join(BASE_DIR, "entities", scenario_id, "npcs")
    if not os.path.exists(npc_dir):
        return

    # game_state NPC ID 목록
    state_npc_ids = {n["id"] for n in state.get("npcs", [])}

    # 엔티티 파일 NPC ID 목록
    entity_npc_ids = set()
    for fname in os.listdir(npc_dir):
        if fname.startswith("npc_") and fname.endswith(".json"):
            try:
                nid = fname.replace("npc_", "").replace(".json", "")
                entity_npc_ids.add(int(nid) if nid.isdigit() else nid)
            except ValueError:
                entity_npc_ids.add(nid)

    # 엔티티 있지만 game_state에 없는 NPC
    orphan_entities = entity_npc_ids - state_npc_ids
    if orphan_entities:
        turn = state.get("turn_count", 0)
        if turn == 0 and FIX_MODE:
            # 새 게임 상태(턴 0)에서 고아 엔티티 → monster만 정리, 세계관 NPC 보존
            removed = 0
            preserved = []
            for oid in orphan_entities:
                orphan_path = os.path.join(npc_dir, f"npc_{oid}.json")
                if os.path.exists(orphan_path):
                    try:
                        npc_data = load_json_safe(orphan_path)
                        if npc_data and npc_data.get("type") == "monster":
                            os.remove(orphan_path)
                            removed += 1
                        else:
                            preserved.append(npc_data.get("name", str(oid)) if npc_data else str(oid))
                    except Exception:
                        preserved.append(str(oid))
            if removed:
                log("warn", f"이전 플레이 잔존 monster 엔티티 {removed}개 자동 정리 (턴 0)", auto_fixed=True)
            if preserved:
                log("ok", f"세계관 NPC 보존: {', '.join(preserved)}")
        else:
            log("warn", f"엔티티 파일은 있지만 game_state에 없는 NPC: {orphan_entities}")
    else:
        log("ok", "고아 NPC 엔티티 없음")


def check_npc_temporal_consistency(state):
    """연계 시나리오 간 NPC 시간 정합성 검증.
    이전 시나리오에서 죽은 NPC가 현재 시나리오에서 살아있으면 경고."""
    print("\n[11] NPC 시간 정합성 검증")
    if state is None:
        return

    scenario_id = state.get("game_info", {}).get("scenario_id", "")
    if not scenario_id:
        return

    # 현재 시나리오의 선행 시나리오 확인
    idx = load_json_safe("scenarios/index.json")
    if not idx:
        log("ok", "scenarios/index.json 없음 — 시간 검증 스킵")
        return

    entry = next((s for s in idx.get("scenarios", []) if s["id"] == scenario_id), None)
    if not entry or not entry.get("prerequisite"):
        log("ok", "선행 시나리오 없음 — 시간 검증 불필요")
        return

    prev_scenario = entry["prerequisite"]

    # 이전 시나리오의 최신 세이브에서 NPC 상태 확인
    prev_save_path = None
    saves_dir = os.path.join(BASE_DIR, "saves")
    for slot_name in ["slot_complete", "slot_1"]:
        candidate = os.path.join(saves_dir, prev_scenario, slot_name, "save.json")
        if os.path.exists(candidate):
            prev_save_path = candidate
            break

    if not prev_save_path:
        log("ok", f"이전 시나리오 '{prev_scenario}' 세이브 없음 — 시간 검증 스킵")
        return

    prev_save = load_json_safe(prev_save_path)
    if not prev_save:
        return

    prev_npcs = prev_save.get("game_state", {}).get("npcs", [])
    # 이전에서 dead인 세계관 NPC 목록
    prev_dead = {n["name"] for n in prev_npcs
                 if n.get("status") in ("dead", "removed") and n.get("type") != "monster"}

    if not prev_dead:
        log("ok", f"이전 시나리오 '{prev_scenario}'에서 사망한 세계관 NPC 없음")
        return

    # 현재 시나리오에서 alive인 NPC와 대조
    current_npcs = state.get("npcs", [])
    violations = []
    for npc in current_npcs:
        if npc.get("name") in prev_dead and npc.get("status") in ("alive", "active", "idle"):
            violations.append(npc["name"])

    if violations:
        log("error", f"시간 모순: 이전 시나리오({prev_scenario})에서 사망했지만 현재 alive인 NPC: {', '.join(violations)}")
        if FIX_MODE:
            for npc in current_npcs:
                if npc.get("name") in violations:
                    npc["status"] = "dead"
            log("warn", f"사망 NPC {len(violations)}명 status를 dead로 수정", auto_fixed=True)
    else:
        log("ok", f"NPC 시간 정합성 통과 (이전 사망: {', '.join(prev_dead)})")


def check_rules_consistency(state):
    """룰 기반 데이터 일관성 검증."""
    print("\n[12] 룰 일관성 검증")
    if state is None:
        return

    rules = load_json_safe("data/rules.json")

    for p in state.get("players", []):
        name = p.get("name", "?")
        stat_cap = 20
        if rules:
            stat_cap = rules.get("stat_cap", rules.get("rules", {}).get("stat_cap", 20))
        for stat_name, stat_val in p.get("stats", {}).items():
            if isinstance(stat_val, (int, float)) and stat_val > stat_cap:
                log("warn", f"{name}의 {stat_name}={stat_val} > 상한({stat_cap})")
                if FIX_MODE:
                    p["stats"][stat_name] = stat_cap
                    log("warn", f"{name}의 {stat_name}을 {stat_cap}로 조정", auto_fixed=True)

        if p.get("hp", 0) < 0:
            log("error", f"{name}의 HP={p['hp']} 음수")
            if FIX_MODE:
                p["hp"] = 0
                log("warn", f"{name}의 HP를 0으로 조정", auto_fixed=True)
        if p.get("mp", 0) < 0:
            log("error", f"{name}의 MP={p['mp']} 음수")
            if FIX_MODE:
                p["mp"] = 0
                log("warn", f"{name}의 MP를 0으로 조정", auto_fixed=True)

        level = p.get("level", 1)
        xp = p.get("xp", 0)
        if rules:
            xp_table = rules.get("xp_table", rules.get("rules", {}).get("xp_table", {}))
            if xp_table:
                expected_level = 1
                for lv_str, req_xp in sorted(xp_table.items(), key=lambda x: int(x[0])):
                    if xp >= req_xp:
                        expected_level = int(lv_str)
                if level != expected_level:
                    log("warn", f"{name} 레벨 불일치: 현재 Lv{level}, XP({xp}) 기준 Lv{expected_level}")

    for npc in state.get("npcs", []):
        name = npc.get("name", "?")
        if npc.get("hp", 0) > npc.get("max_hp", 999):
            log("warn", f"NPC {name}의 HP({npc['hp']}) > max_hp({npc['max_hp']})")
            if FIX_MODE:
                npc["hp"] = npc["max_hp"]
                log("warn", f"NPC {name} HP를 max_hp로 조정", auto_fixed=True)
        if npc.get("hp", 0) < 0 and npc.get("status") == "alive":
            log("error", f"NPC {name}의 HP={npc['hp']} 음수인데 status=alive")
            if FIX_MODE:
                npc["hp"] = 0
                npc["status"] = "dead"
                log("warn", f"NPC {name} status를 dead로 변경", auto_fixed=True)

    log("ok", "룰 일관성 검증 완료")


def check_save_integrity(state):
    """세이브 파일 정합성 검증 (2중 안전망)."""
    print("\n[13] 세이브 파일 정합성 검증")
    saves_dir = os.path.join(BASE_DIR, "saves")
    if not os.path.exists(saves_dir):
        log("ok", "세이브 디렉토리 없음 (새 게임)")
        return

    save_count = 0
    for sid in sorted(os.listdir(saves_dir)):
        sid_path = os.path.join(saves_dir, sid)
        if not os.path.isdir(sid_path):
            continue
        for slot_dir in sorted(os.listdir(sid_path)):
            if not slot_dir.startswith("slot_"):
                continue
            save_file = os.path.join(sid_path, slot_dir, "save.json")
            if not os.path.exists(save_file):
                continue
            save_count += 1

            save_data = load_json_safe(save_file)
            if save_data is None:
                log("error", f"{sid}/{slot_dir}: 세이브 파일 파싱 실패")
                continue

            info = save_data.get("save_info", {})
            gs = save_data.get("game_state", {})
            gi = gs.get("game_info", {})

            # 1. scenario_id 일치 (폴더 vs save_info vs game_state)
            info_sid = info.get("scenario_id", "")
            gs_sid = gi.get("scenario_id", "")
            if info_sid and info_sid != sid:
                log("error", f"{sid}/{slot_dir}: save_info.scenario_id='{info_sid}' ≠ 폴더='{sid}'")
                if FIX_MODE:
                    info["scenario_id"] = sid
                    save_json(save_file, save_data)
                    log("warn", f"{sid}/{slot_dir}: save_info.scenario_id를 '{sid}'로 수정", auto_fixed=True)
            elif info_sid:
                log("ok", f"{sid}/{slot_dir}: scenario_id 일치 ({info_sid})")

            if gs_sid and gs_sid != sid:
                log("error", f"{sid}/{slot_dir}: game_state.scenario_id='{gs_sid}' ≠ 폴더='{sid}'")
                if FIX_MODE:
                    gi["scenario_id"] = sid
                    save_json(save_file, save_data)
                    log("warn", f"{sid}/{slot_dir}: game_state.scenario_id를 '{sid}'로 수정", auto_fixed=True)

            # 2. current_location 존재
            loc = gs.get("current_location")
            if not loc:
                log("warn", f"{sid}/{slot_dir}: current_location 비어있음")

            # 3. 필수 키 존재
            for key in ["players", "npcs", "events"]:
                if key not in gs:
                    log("error", f"{sid}/{slot_dir}: game_state.{key} 누락")

            # 4. 시나리오 파일과 NPC 대조 (타 시나리오 NPC 오염 감지)
            scenario_path = os.path.join(BASE_DIR, "scenarios", f"{sid}.json")
            if os.path.exists(scenario_path):
                sc = load_json_safe(scenario_path)
                if sc:
                    valid_npc_names = {n.get("name") for n in sc.get("default_npcs", [])}
                    # 몬스터/임시 NPC는 제외, friendly/quest NPC만 체크
                    for npc in gs.get("npcs", []):
                        if npc.get("type") in ("monster",):
                            continue
                        if npc.get("status") in ("dead", "removed", "fled"):
                            continue
                        npc_name = npc.get("name", "")
                        if npc_name and valid_npc_names and npc_name not in valid_npc_names:
                            log("warn", f"{sid}/{slot_dir}: NPC '{npc_name}'이 시나리오 default_npcs에 없음 (타 시나리오 오염?)")

            # 5. 플레이어 HP/MP 범위
            for p in gs.get("players", []):
                pname = p.get("name", "?")
                if p.get("hp", 0) > p.get("max_hp", 999):
                    log("warn", f"{sid}/{slot_dir}: {pname} HP({p['hp']}) > max_hp({p['max_hp']})")
                if p.get("mp", 0) > p.get("max_mp", 999):
                    log("warn", f"{sid}/{slot_dir}: {pname} MP({p['mp']}) > max_mp({p['max_mp']})")

    if save_count == 0:
        log("ok", "세이브 파일 없음 (새 게임)")
    else:
        log("ok", f"세이브 파일 {save_count}개 검증 완료")


def check_quest_consistency(state):
    """퀘스트 상태 일관성 검증."""
    print("\n[14] 퀘스트 상태 검증")
    quests = load_json_safe("data/quests.json")
    if quests is None:
        log("ok", "quests.json 없음 (퀘스트 미사용)")
        return

    raw_quests = quests if isinstance(quests, list) else quests.get("quests", [])
    quest_list = raw_quests if isinstance(raw_quests, list) else list(raw_quests.values()) if isinstance(raw_quests, dict) else []
    active = [q for q in quest_list if q.get("status") == "active"]
    completed = [q for q in quest_list if q.get("status") == "completed"]
    failed = [q for q in quest_list if q.get("status") == "failed"]
    log("ok", f"퀘스트 현황: 활성 {len(active)}, 완료 {len(completed)}, 실패 {len(failed)}")

    for q in active:
        qid = q.get("id", q.get("title", "?"))
        if not q.get("objective") and not q.get("objectives"):
            log("warn", f"활성 퀘스트 '{qid}'에 objective 없음")


# ─── 자동 수정 헬퍼 ───

def _create_player_entity(scenario_id, player):
    """누락된 플레이어 엔티티 생성."""
    ent_dir = os.path.join(BASE_DIR, "entities", scenario_id, "players")
    os.makedirs(ent_dir, exist_ok=True)
    entity = {
        "id": player["id"],
        "name": player.get("name", f"Player_{player['id']}"),
        "class": player.get("class", ""),
        "level": player.get("level", 1),
        "background": {"origin": "", "motivation": "", "personality": ""},
        "stats": player.get("stats", {}),
        "hp": player.get("hp", player.get("max_hp", 10)),
        "max_hp": player.get("max_hp", 10),
        "mp": player.get("mp", player.get("max_mp", 5)),
        "max_mp": player.get("max_mp", 5),
        "position": player.get("position", [0, 0]),
        "status_effects": player.get("status_effects", []),
        "inventory": player.get("inventory", []),
        "equipment": {},
        "available_actions": [],
        "combat_state": {"is_in_combat": False, "defense_bonus": 0, "next_turn_penalty": 0},
        "history": {
            "actions_taken": [], "damage_dealt_total": 0, "damage_received_total": 0,
            "kills": [], "items_used": [], "turns_played": 0
        },
        "conditions": {"alive": True, "conscious": True, "death_save_turns": 0},
        "controlled_by": player.get("controlled_by", "agent"),
    }
    save_json(os.path.join(ent_dir, f"player_{player['id']}.json"), entity)


def _create_npc_entity(scenario_id, npc):
    """누락된 NPC 엔티티 생성. game_mechanics.create_npc_entity와 호환."""
    npc_dir = os.path.join(BASE_DIR, "entities", scenario_id, "npcs")
    os.makedirs(npc_dir, exist_ok=True)

    npc_type = npc.get("type", "neutral")
    entity = {
        "id": npc["id"],
        "name": npc.get("name", f"NPC_{npc['id']}"),
        "type": npc_type,
        "status": npc.get("status", "alive"),
        "location": npc.get("location", ""),
        "personality": npc.get("personality", {
            "temperament": "neutral", "intelligence": "medium",
            "behavior_pattern": "", "speech_style": "", "motivation": ""
        }),
        "relationships": npc.get("relationships", {}),
        "memory": npc.get("memory", {"dialogue_history": [], "key_events": []}),
    }
    if npc.get("stats"):
        entity["stats"] = npc["stats"]
    if npc.get("hp") or npc.get("max_hp"):
        entity["hp"] = npc.get("hp", npc.get("max_hp", 10))
        entity["max_hp"] = npc.get("max_hp", 10)
    if npc.get("position"):
        entity["position"] = npc["position"]

    save_json(os.path.join(npc_dir, f"npc_{npc['id']}.json"), entity)


# ─── 메인 ───

def main():
    global FIX_MODE, VERBOSE

    # 인자 파싱
    if "--check" in sys.argv:
        FIX_MODE = False
    if "--verbose" in sys.argv:
        VERBOSE = True

    mode_str = "검증 + 자동 수정" if FIX_MODE else "검증만 (읽기 전용)"
    print(f"=== TRPG 세션 검증기 ({mode_str}) ===")

    # 순차 실행 (각 검증 항목이 이전 결과에 의존)
    state = check_game_state()
    session = check_current_session(state)
    check_player_entities(state)
    check_npc_entities(state)
    check_scenario_files(state)
    check_worldbuilding(state)
    check_entity_directory_structure(state)
    check_orphan_npcs(state)
    check_npc_temporal_consistency(state)
    check_services()
    check_illustrations(state)
    check_rules_consistency(state)
    check_save_integrity(state)
    check_quest_consistency(state)

    # 자동 수정된 game_state 저장
    if FIX_MODE and state is not None and results["fixed"] > 0:
        save_json("data/game_state.json", state)
        print(f"\n  [INFO] game_state.json에 수정 사항 저장 완료")

    # 결과 요약
    print(f"\n{'='*40}")
    print(f"  검증 결과 요약")
    print(f"{'='*40}")
    print(f"  [OK]    {results['ok']}")
    print(f"  [WARN]  {results['warn']}")
    print(f"  [ERROR] {results['error']}")
    if FIX_MODE:
        print(f"  [AUTO-FIXED] {results['fixed']}")
    print()

    if results["error"] > 0:
        print("  !! 에러가 있습니다. 수동 확인이 필요합니다.")
        return 1
    elif results["warn"] > 0:
        print("  주의 사항이 있지만 게임 진행에 지장 없습니다.")
        return 0
    else:
        print("  모든 검증 통과! 게임을 이어서 진행하세요.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
