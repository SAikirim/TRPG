#!/usr/bin/env python
"""
TRPG 게임 시작 자동화
- 시나리오 선택, 새 게임/이어하기/세이브 로드를 CLI에서 처리
- 엔티티 생성, game_state 초기화, 맵 생성, 장면 복원까지 자동 실행

사용법:
  python game_start.py                                      # 대화형: 시나리오 목록 표시, 선택
  python game_start.py new lost_treasure                    # 특정 시나리오로 새 게임
  python game_start.py continue karendel_journey --from lost_treasure  # 이전 시나리오에서 이어하기
  python game_start.py load                                 # 세이브 목록에서 로드
"""
import json
import os
import sys
import shutil
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def load_json(path):
    """JSON 파일 로드. 상대 경로는 BASE_DIR 기준."""
    full = path if os.path.isabs(path) else os.path.join(BASE_DIR, path)
    with open(full, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    """JSON 파일 저장. 상대 경로는 BASE_DIR 기준."""
    full = path if os.path.isabs(path) else os.path.join(BASE_DIR, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ─── 유틸리티 ───

def _get_agent_name(agent_id):
    """에이전트 ID로 에이전트 이름 조회. agents/{agent_id}.json에서 name 필드."""
    try:
        agent = load_json(f"agents/{agent_id}.json")
        return agent.get("name", agent_id)
    except (FileNotFoundError, json.JSONDecodeError):
        return agent_id


# ─── 세이브 파일 표시 ───

def _show_existing_saves():
    """기존 세이브 파일 목록을 표시한다."""
    saves_dir = os.path.join(BASE_DIR, "saves")
    if not os.path.exists(saves_dir):
        return
    saves = []
    for sid in sorted(os.listdir(saves_dir)):
        sid_dir = os.path.join(saves_dir, sid)
        if not os.path.isdir(sid_dir):
            continue
        for slot_name in sorted(os.listdir(sid_dir)):
            if not slot_name.startswith("slot_"):
                continue
            sf = os.path.join(sid_dir, slot_name, "save.json")
            if os.path.exists(sf):
                try:
                    with open(sf, "r", encoding="utf-8") as f:
                        info = json.load(f).get("save_info", {})
                    saves.append((sid, slot_name, info))
                except Exception:
                    pass
    if not saves:
        print("\n  (저장된 세이브 없음)")
        return
    print(f"\n{'='*50}")
    print(f"  기존 세이브 파일")
    print(f"{'='*50}")
    for sid, slot_name, info in saves:
        slot_num = slot_name.replace("slot_", "#")
        desc = info.get("description", "") or "(설명 없음)"
        turn = info.get("turn_count", "?")
        chapter = f"Ch.{info.get('chapter', '?')}" if info.get("chapter") else ""
        saved_at = info.get("saved_at", "")
        print(f"  {sid}  슬롯{slot_num}  {desc}  턴 {turn}  {chapter}  {saved_at}")
    print(f"  → 세이브 로드: L 입력")
    print()


# ─── 시나리오 목록 ───

def list_scenarios():
    """scenarios/index.json에서 시나리오 목록을 표시하고 반환."""
    index = load_json("scenarios/index.json")
    scenarios = index["scenarios"]
    print("\n=== 시나리오 목록 ===")
    for i, s in enumerate(scenarios):
        prereq = f" (선행: {s['prerequisite']})" if s.get("prerequisite") else ""
        standalone = " [단독 플레이 가능]" if s.get("standalone") else ""
        print(f"  [{i+1}] {s['title']} (Lv.{s['recommended_level']}, {s['difficulty']}){prereq}{standalone}")
    return scenarios


# ─── HP/MP 계산 ───

def calculate_hp_mp(player, classes_data):
    """character_classes.json의 공식으로 HP/MP 계산.
    공식: hp = hp_base + floor(CON * hp_per_con)
          mp = mp_base + floor(INT * mp_per_int)
    """
    cls_name = player["class"]
    cls = classes_data.get("classes", {}).get(cls_name, {})
    con = player.get("stats", {}).get("CON", 10)
    int_stat = player.get("stats", {}).get("INT", 10)

    # 시나리오 default_party에 hp_base가 직접 있으면 우선 사용
    hp_base = player.get("hp_base", cls.get("hp_base", 10))
    mp_base = player.get("mp_base", cls.get("mp_base", 5))
    hp_per_con = cls.get("hp_per_con", 0.5)
    mp_per_int = cls.get("mp_per_int", 0)

    hp = hp_base + int(con * hp_per_con)
    mp = mp_base + int(int_stat * mp_per_int)
    return hp, mp


# ─── 엔티티 생성 ───

def create_entities(scenario_id, players, npcs):
    """시나리오용 엔티티 디렉토리와 파일을 생성.
    새 게임이므로 일회성 NPC(monster)를 정리하고, 세계관 NPC(friendly/neutral)는 보존한다."""
    ent_dir = os.path.join(BASE_DIR, "entities", scenario_id)
    for sub in ["players", "npcs", "objects"]:
        sub_dir = os.path.join(ent_dir, sub)
        os.makedirs(sub_dir, exist_ok=True)
        # 새 게임: 일회성 엔티티만 정리 (오브젝트는 전부, NPC는 monster만)
        if sub == "objects":
            for old_file in os.listdir(sub_dir):
                if old_file.endswith(".json"):
                    os.remove(os.path.join(sub_dir, old_file))
        elif sub == "npcs":
            for old_file in os.listdir(sub_dir):
                if not old_file.endswith(".json"):
                    continue
                fpath = os.path.join(sub_dir, old_file)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        npc_data = json.load(f)
                    # monster 타입만 삭제, friendly/neutral 등 세계관 NPC는 보존
                    if npc_data.get("type") == "monster":
                        os.remove(fpath)
                except (json.JSONDecodeError, KeyError):
                    pass  # 파싱 실패 시 보존

    # 플레이어 엔티티
    for p in players:
        entity = {
            "id": p["id"],
            "name": p["name"],
            "class": p["class"],
            "level": p.get("level", 1),
            "background": p.get("background", {"origin": "", "motivation": "", "personality": ""}),
            "stats": p.get("stats", {}),
            "hp": p.get("hp", p.get("max_hp", 10)),
            "max_hp": p.get("max_hp", 10),
            "mp": p.get("mp", p.get("max_mp", 5)),
            "max_mp": p.get("max_mp", 5),
            "position": p.get("position", [0, 0]),
            "status_effects": [],
            "inventory": p.get("inventory", []),
            "equipment": p.get("equipment", {}),
            "available_actions": p.get("available_actions", []),
            "combat_state": {"is_in_combat": False, "defense_bonus": 0, "next_turn_penalty": 0},
            "history": {
                "actions_taken": [], "damage_dealt_total": 0, "damage_received_total": 0,
                "kills": [], "items_used": [], "turns_played": 0
            },
            "conditions": {"alive": True, "conscious": True, "death_save_turns": 0},
            "controlled_by": p.get("controlled_by", "ai"),
            "race": p.get("race", "인간"),
            "appearance": p.get("appearance", {}),
        }
        # 선택적 확장 필드 (에이전트 시스템)
        if p.get("agent_id"):
            entity["agent_id"] = p["agent_id"]
        save_json(f"entities/{scenario_id}/players/player_{p['id']}.json", entity)

    # NPC 엔티티 — game_mechanics.create_npc_entity 호환 구조
    for n in npcs:
        npc_type = n.get("type", "neutral")
        entity = {
            "id": n["id"],
            "name": n["name"],
            "type": npc_type,
            "status": n.get("status", "alive"),
            "location": n.get("location", ""),
            "personality": n.get("personality", {
                "temperament": "neutral", "intelligence": "medium",
                "behavior_pattern": "", "speech_style": "", "motivation": ""
            }),
            "relationships": n.get("relationships", {}),
            "memory": n.get("memory", {"dialogue_history": [], "key_events": []}),
        }
        # 전투 스탯
        if n.get("stats"):
            entity["stats"] = n["stats"]
        if n.get("hp") or n.get("max_hp"):
            entity["hp"] = n.get("hp", n.get("max_hp", 10))
            entity["max_hp"] = n.get("max_hp", 10)
        if n.get("mp") or n.get("max_mp"):
            entity["mp"] = n.get("mp", 0)
            entity["max_mp"] = n.get("max_mp", 0)
        if n.get("position"):
            entity["position"] = n["position"]
        # 추가 필드 병합
        for key in ("conditions", "equipment", "inventory", "attack", "defense", "threat_level"):
            if key in n:
                entity[key] = n[key]
        # 외형 (SD 초상화 자동 생성용)
        if n.get("race"):
            entity["race"] = n["race"]
        if n.get("appearance"):
            entity["appearance"] = n["appearance"]

        save_json(f"entities/{scenario_id}/npcs/npc_{n['id']}.json", entity)

    print(f"  엔티티 생성 완료: players={len(players)}, npcs={len(npcs)}")


# ─── 새 게임 ───

def new_game(scenario_id, skip_mode_select=False, party=None):
    """새 게임 시작. 시나리오 로드 → 룰셋 선택 → 시작 모드 → 캐릭터 메이킹 → 상태 초기화.

    Args:
        scenario_id: 시나리오 ID (예: "lost_treasure")
        skip_mode_select: True면 시작 모드 선택 건너뜀 (CLI 전용)
        party: 외부에서 주입하는 파티 데이터 (리스트). 주어지면 대화형 캐릭터 메이킹 스킵.
            각 항목: {"id":1, "name":"가온", "class":"전사", "stats":{"STR":18,...},
                      "controlled_by":"ai", "agent_id":"agent_a", "background":{...},
                      "appearance":{...}, "race":"인간"}
            HP/MP는 stats + character_classes.json 공식으로 자동 계산됨.
    """
    index = load_json("scenarios/index.json")
    scenario_entry = next((s for s in index["scenarios"] if s["id"] == scenario_id), None)
    if not scenario_entry:
        print(f"[ERROR] 시나리오 '{scenario_id}'를 찾을 수 없습니다.")
        print(f"  등록된 시나리오: {[s['id'] for s in index['scenarios']]}")
        return False

    # 시나리오 파일 로드
    scenario_file = scenario_entry.get("scenario_file", f"{scenario_id}.json")
    # 여러 경로 시도: scenarios/{file}, {file}, scenarios/{id}.json
    candidates = [
        os.path.join("scenarios", scenario_file),
        scenario_file,
        os.path.join("scenarios", f"{scenario_id}.json"),
    ]
    resolved = None
    for c in candidates:
        if os.path.exists(os.path.join(BASE_DIR, c)):
            resolved = c
            break
    if resolved is None:
        print(f"[ERROR] 시나리오 파일을 찾을 수 없습니다: {scenario_id}")
        print(f"  시도한 경로: {candidates}")
        print(f"  scenarios/index.json의 scenario_file 값을 확인하세요.")
        return False
    scenario = load_json(resolved)

    # initial_state 로드
    initial_file = scenario_entry.get("initial_state", "data/game_state_initial.json")
    if not os.path.exists(os.path.join(BASE_DIR, initial_file)):
        # 폴백: data/game_state_initial.json
        initial_file = "data/game_state_initial.json"
    if not os.path.exists(os.path.join(BASE_DIR, initial_file)):
        print(f"[ERROR] initial_state 파일을 찾을 수 없습니다: {initial_file}")
        return False
    state = load_json(initial_file)

    # ─── 룰셋 선택 ───
    ruleset_index = load_json("rulesets/index.json")
    rulesets = ruleset_index.get("rulesets", [])
    # 시나리오 권장 룰셋 (index.json의 ruleset 필드)
    recommended_ruleset = scenario_entry.get("ruleset", ruleset_index.get("default_ruleset", ""))

    if len(rulesets) == 1:
        # 룰셋이 하나뿐이면 자동 선택
        chosen_ruleset = rulesets[0]
        print(f"\n=== 룰셋 선택 ===")
        print(f"  [1] {chosen_ruleset['title']} — {chosen_ruleset['description']}")
        print(f"  -> 룰셋이 1개뿐이므로 자동 선택: {chosen_ruleset['title']}")
    else:
        print(f"\n=== 룰셋 선택 ===")
        for i, r in enumerate(rulesets, 1):
            rec = " (권장)" if r["id"] == recommended_ruleset else ""
            print(f"  [{i}] {r['title']} — {r['description']}{rec}")
        try:
            choice = input(f"\n룰셋 번호 선택 (빈칸={recommended_ruleset}): ").strip()
            if not choice:
                chosen_ruleset = next((r for r in rulesets if r["id"] == recommended_ruleset), rulesets[0])
            else:
                chosen_ruleset = rulesets[int(choice) - 1]
        except (ValueError, IndexError, EOFError):
            chosen_ruleset = next((r for r in rulesets if r["id"] == recommended_ruleset), rulesets[0])
        print(f"  -> {chosen_ruleset['title']}")

    # 룰셋 파일 복사 → data/rules.json
    ruleset_file = chosen_ruleset.get("rules_file", f"{chosen_ruleset['id']}.json")
    ruleset_src = os.path.join(BASE_DIR, "rulesets", ruleset_file)
    if os.path.exists(ruleset_src):
        import shutil
        shutil.copy2(ruleset_src, os.path.join(BASE_DIR, "data", "rules.json"))
    state["game_info"]["ruleset"] = chosen_ruleset["id"]

    # ─── 시작 모드 결정 (main 대화형에서 이미 처리된 경우 스킵) ───
    if not skip_mode_select:
        result = _start_mode_select(scenario_id, scenario)
        if result == "load":
            return True  # 세이브 로드 완료, 새 게임 불필요
    else:
        print(f"\n=== 시작 모드 ===")
        print(f"  -> 새 게임으로 시작합니다.")

    # 클래스 데이터 로드
    classes = load_json("templates/character_classes.json")

    # ─── 캐릭터 메이킹 ───
    if party:
        # 외부 주입 파티 (에이전트 대화 결과, API 호출 등)
        # HP/MP 자동 계산 + _build_player로 정규화
        players = _build_party_from_data(party, scenario, classes)
        print(f"\n=== 파티 등록 (외부 주입) ===")
        for p in players:
            ctrl = "USER" if p.get("controlled_by") == "user" else "AI"
            agent = f" ({p['agent_id']})" if p.get("agent_id") else ""
            stats_str = " ".join(f"{k}:{v}" for k, v in p["stats"].items())
            print(f"  {p['name']} ({p['class']}) [{ctrl}{agent}] HP:{p['hp']}/{p['max_hp']} MP:{p['mp']}/{p['max_mp']} {stats_str}")
    else:
        # 대화형 CLI 캐릭터 메이킹 (기존)
        players = _character_making(scenario, classes, state)

    # game_state 구성
    state["players"] = players
    state["game_info"]["scenario_id"] = scenario_id
    state["game_info"]["title"] = scenario["scenario_info"]["title"]
    state["game_info"]["status"] = "active"
    state["game_info"]["current_chapter"] = 1
    state["game_info"]["ending"] = None
    state["turn_count"] = 0

    # NPC 설정
    npcs = scenario.get("default_npcs", [])
    state["npcs"] = npcs

    # current_location 설정
    if scenario.get("chapters") and scenario["chapters"][0].get("map_area"):
        state["current_location"] = scenario["chapters"][0]["map_area"]

    # 오프닝 이벤트
    opening_narrative = scenario.get("opening", {}).get("narrative", "")
    state["events"] = [{
        "turn": 0,
        "message": f"[시스템] 새 게임 시작: {scenario['scenario_info']['title']}",
        "narrative": opening_narrative,
        "timestamp": datetime.now().strftime("%H:%M:%S"),
    }]

    # game_state.json 저장
    save_json("data/game_state.json", state)
    print(f"\n  [OK] game_state.json 저장 완료")

    # 엔티티 생성
    create_entities(scenario_id, players, npcs)

    # current_session.json 갱신
    chapter_name = scenario["chapters"][0]["name"] if scenario.get("chapters") else ""
    session = {
        "active_scenario": scenario_id,
        "active_save_slot": 1,
        "ruleset": scenario["scenario_info"].get("ruleset", scenario_entry.get("ruleset", "fantasy_basic")),
        "worldbuilding": scenario_entry.get("worldbuilding", ""),
        "turn": 0,
        "chapter": 1,
        "chapter_name": chapter_name,
        "status": "active",
        "party_summary": [
            {
                "name": p["name"], "class": p["class"],
                "hp": f"{p['hp']}/{p['max_hp']}", "mp": f"{p['mp']}/{p['max_mp']}",
                "key_items": p.get("inventory", [])[:5],
                **( {"agent": _get_agent_name(p["agent_id"])} if p.get("agent_id") else {} )
            }
            for p in players
        ],
        "progress_notes": [f"새 게임 시작: {scenario['scenario_info']['title']}"],
        "next_objective": scenario.get("chapters", [{}])[0].get("description", "") if scenario.get("chapters") else "",
        "display_mode": "mobile",
        "show_dice_result": False,
        "sd_illustration": True,
        "last_updated": datetime.now().strftime("%Y-%m-%d"),
    }
    save_json("data/current_session.json", session)
    print(f"  [OK] current_session.json 저장 완료")

    # 활성 시나리오/룰셋 파일 복사 (scenario.json, rules.json)
    _activate_scenario_files(scenario_entry, resolved, ruleset_override=chosen_ruleset["id"])

    # 세계관 활성화 (worldbuildings/ → data/worldbuilding.json)
    _activate_worldbuilding(scenario_entry)

    # 맵 생성
    try:
        from core.map_generator import MapGenerator
        MapGenerator().save_map()
        print(f"  [OK] 맵 생성 완료")
    except Exception as e:
        print(f"  [WARN] 맵 생성 실패 (수동 실행 필요): {e}")

    # 사전 이미지 생성 (SD 또는 Cairo)
    try:
        from core.sd_generator import pre_generate_images
        print("\n=== 사전 이미지 생성 ===")
        gen_result = pre_generate_images(scenario_id)
        print(f"  [OK] 생성: {gen_result['generated']}장, 재활용: {gen_result['skipped']}장")
        if gen_result['errors']:
            for err in gen_result['errors']:
                print(f"  [WARN] {err}")
    except Exception as e:
        print(f"  [WARN] 사전 이미지 생성 실패 (게임 진행에 영향 없음): {e}")

    # Flask 장면 복원 시도
    _try_restore_scene()

    # 오프닝 출력
    print(f"\n{'='*50}")
    print(f"  {scenario['scenario_info']['title']}")
    print(f"{'='*50}")
    if scenario.get("opening", {}).get("new_game"):
        print(f"\n{scenario['opening']['new_game']}")
    if opening_narrative:
        print(f"\n{opening_narrative}")
    print(f"\n게임 시작! (턴 0, 챕터 1: {chapter_name})")
    print(f"Flask 서버: start_server.bat 또는 SD venv Python app.py -> http://localhost:5000")
    _print_state_summary(state)

    print(f"⚠️  다음 단계: GM 턴 0 (오프닝 나레이션) 진행 필요")
    print(f"   game_start.py는 데이터만 초기화합니다.")
    print(f"   GM이 오프닝 나레이션을 진행해야 캐릭터가 세계에 등장합니다.")
    print(f"   (CLAUDE.md '새 게임 오프닝' 참조)\n")

    # 정적 웹 동기화
    _sync_docs()
    return True


# ─── 이어하기 ───

def continue_game(scenario_id, from_scenario):
    """이전 시나리오의 세이브에서 캐릭터를 이어받아 새 시나리오 시작."""
    # 이전 세이브 찾기 (slot_complete 우선, 없으면 slot_1)
    save_path = None
    for slot_name in ["slot_complete", "slot_1"]:
        candidate = os.path.join(BASE_DIR, "saves", from_scenario, slot_name, "save.json")
        if os.path.exists(candidate):
            save_path = candidate
            break

    if not save_path:
        print(f"[ERROR] '{from_scenario}' 세이브 데이터를 찾을 수 없습니다.")
        print(f"  확인 경로: saves/{from_scenario}/slot_complete/ 또는 saves/{from_scenario}/slot_1/")
        return False

    # 이전 세이브 로드
    with open(save_path, "r", encoding="utf-8") as f:
        prev_save = json.load(f)
    prev_players = prev_save["game_state"]["players"]
    print(f"\n=== 이전 시나리오 '{from_scenario}' 에서 캐릭터 이어받기 ===")
    for pp in prev_players:
        print(f"  {pp['name']} ({pp['class']}) Lv.{pp.get('level',1)} HP:{pp['hp']}/{pp['max_hp']} MP:{pp['mp']}/{pp['max_mp']}")
        if pp.get("inventory"):
            print(f"    인벤토리: {', '.join(pp['inventory'][:5])}{'...' if len(pp.get('inventory',[])) > 5 else ''}")

    # 먼저 새 게임으로 기본 상태 생성
    if not new_game(scenario_id):
        return False

    # 이전 캐릭터 데이터로 오버라이드
    state = load_json("data/game_state.json")
    for prev_p in prev_players:
        for curr_p in state["players"]:
            if curr_p["id"] == prev_p["id"]:
                curr_p.update({
                    "name": prev_p["name"],
                    "level": prev_p.get("level", 1),
                    "xp": prev_p.get("xp", 0),
                    "hp": prev_p["hp"],
                    "max_hp": prev_p["max_hp"],
                    "mp": prev_p["mp"],
                    "max_mp": prev_p["max_mp"],
                    "stats": prev_p["stats"],
                    "inventory": prev_p.get("inventory", []),
                    "status_effects": prev_p.get("status_effects", []),
                    "controlled_by": prev_p.get("controlled_by", "ai"),
                })
                break
    save_json("data/game_state.json", state)

    # 엔티티 파일도 이어받기 데이터로 갱신
    for p in state["players"]:
        ent_path = os.path.join(BASE_DIR, "entities", scenario_id, "players", f"player_{p['id']}.json")
        if os.path.exists(ent_path):
            ent = load_json(ent_path)
            ent.update({
                "name": p["name"],
                "level": p.get("level", 1),
                "stats": p["stats"],
                "hp": p["hp"],
                "max_hp": p["max_hp"],
                "mp": p["mp"],
                "max_mp": p["max_mp"],
                "inventory": p.get("inventory", []),
                "controlled_by": p.get("controlled_by", "ai"),
            })
            save_json(ent_path, ent)

    # ─── 세계관 NPC 상태 이월 (시간 연속성) ───
    _carry_over_npc_states(scenario_id, from_scenario, prev_save, state)

    # current_session 파티 요약 갱신
    session = load_json("data/current_session.json")
    session["party_summary"] = [
        {
            "name": p["name"], "class": p["class"],
            "hp": f"{p['hp']}/{p['max_hp']}", "mp": f"{p['mp']}/{p['max_mp']}",
            "key_items": p.get("inventory", [])[:5]
        }
        for p in state["players"]
    ]
    session["progress_notes"].insert(0, f"'{from_scenario}' 에서 캐릭터 이어받기 완료")
    save_json("data/current_session.json", session)

    print(f"\n  [OK] '{from_scenario}' 에서 캐릭터 데이터 이어받기 완료")
    _print_state_summary(state)

    # 정적 웹 동기화 (캐리오버 데이터 반영)
    _sync_docs()
    return True


# ─── 세이브 로드 ───

def load_game():
    """세이브 목록을 표시하고 선택하여 로드."""
    saves_dir = os.path.join(BASE_DIR, "saves")
    if not os.path.exists(saves_dir):
        print("[ERROR] 세이브 디렉토리가 없습니다.")
        return False

    # 세이브 목록 수집
    all_saves = []
    for sid in sorted(os.listdir(saves_dir)):
        sid_dir = os.path.join(saves_dir, sid)
        if not os.path.isdir(sid_dir):
            continue
        for slot in sorted(os.listdir(sid_dir)):
            if not slot.startswith("slot_"):
                continue
            sf = os.path.join(sid_dir, slot, "save.json")
            if os.path.exists(sf):
                with open(sf, "r", encoding="utf-8") as f:
                    info = json.load(f)["save_info"]
                all_saves.append({
                    "scenario_id": sid,
                    "slot": slot,
                    "info": info,
                })

    if not all_saves:
        print("[ERROR] 저장된 세이브가 없습니다.")
        return False

    print("\n=== 세이브 목록 ===")
    for i, s in enumerate(all_saves):
        info = s["info"]
        slot_num = s['slot'].replace('slot_', '#')
        desc = info.get('description', '') or "(설명 없음)"
        chapter = f"Ch.{info.get('chapter', '?')}" if info.get('chapter') else ""
        print(f"  [{i+1}] {s['scenario_id']}  슬롯{slot_num}  {desc}  턴 {info.get('turn_count', '?')}  {chapter}  {info.get('saved_at', '')}")

    choice = input("\n로드할 세이브 번호 (0=취소): ").strip()
    try:
        idx = int(choice) - 1
        if idx < 0:
            print("취소됨.")
            return False
        selected = all_saves[idx]
    except (ValueError, IndexError):
        print("잘못된 선택입니다.")
        return False

    # 세이브 로드
    sf = os.path.join(saves_dir, selected["scenario_id"], selected["slot"], "save.json")
    with open(sf, "r", encoding="utf-8") as f:
        save_data = json.load(f)

    # game_state.json에 적용
    save_json("data/game_state.json", save_data["game_state"])
    print(f"\n  [OK] 세이브 로드 완료: {selected['scenario_id']}/{selected['slot']}")

    # 맵 갱신
    try:
        from core.map_generator import MapGenerator
        MapGenerator().save_map()
        print(f"  [OK] 맵 갱신 완료")
    except Exception as e:
        print(f"  [WARN] 맵 갱신 실패: {e}")

    # 장면 복원
    _try_restore_scene()

    _print_state_summary(save_data["game_state"])

    # 정적 웹 동기화
    _sync_docs()
    return True


# ─── docs/ 동기화 (정적 웹) ───

def _sync_docs():
    """docs/ 폴더를 최신 상태로 동기화 (GitHub Pages용)."""
    try:
        from core.save_manager import SaveManager
        state = load_json("data/game_state.json")
        sm = SaveManager()
        sm._sync_docs(state)
        print("  [OK] docs/ 동기화 완료 (정적 웹)")
    except Exception as e:
        print(f"  [WARN] docs/ 동기화 실패: {e}")


# ─── 유틸리티 ───

def _activate_scenario_files(scenario_entry, scenario_file, ruleset_override=None):
    """활성 시나리오/룰셋 파일을 data/에 복사 (scenario.json, rules.json)."""
    # scenario.json
    src = os.path.join(BASE_DIR, scenario_file)
    dst = os.path.join(BASE_DIR, "data", "scenario.json")
    if os.path.exists(src) and os.path.abspath(src) != os.path.abspath(dst):
        shutil.copy2(src, dst)
        print(f"  [OK] data/scenario.json <- {scenario_file}")

    # rules.json (룰셋) — 유저가 선택한 룰셋 우선, 없으면 시나리오 기본값
    ruleset_id = ruleset_override or scenario_entry.get("ruleset", "fantasy_basic")
    ruleset_file = f"rulesets/{ruleset_id}.json"
    ruleset_src = os.path.join(BASE_DIR, ruleset_file)
    rules_dst = os.path.join(BASE_DIR, "data", "rules.json")
    if os.path.exists(ruleset_src):
        shutil.copy2(ruleset_src, rules_dst)
        print(f"  [OK] data/rules.json <- {ruleset_file}")


def _character_making(scenario, classes, state):
    """캐릭터 메이킹 플로우.
    1. 기본 파티를 표시
    2. [기본 파티 수락 / 커스텀] 선택
    3. 커스텀: 각 캐릭터의 이름, 클래스, 스탯 조정 가능
    반환: players 리스트
    """
    party = scenario.get("default_party", {}).get("players", [])
    difficulty = state.get("game_info", {}).get("difficulty", "normal")
    stat_pool = classes.get("stat_pool", {}).get("by_difficulty", {}).get(difficulty, 50)
    min_stat = classes.get("stat_pool", {}).get("min_stat", 6)
    max_stat = classes.get("stat_pool", {}).get("max_stat", 18)
    available_classes = list(classes.get("classes", {}).keys())
    auto_names = classes.get("auto_generate", {}).get("name_pool", {})

    # 시나리오 파티 인원 제한
    party_size = scenario.get("scenario_info", {}).get("party_size", {})
    min_party = party_size.get("min", len(party))
    max_party = party_size.get("max", len(party))
    rec_party = party_size.get("recommended", len(party))

    print(f"\n{'='*50}")
    print(f"  캐릭터 메이킹: {scenario['scenario_info']['title']}")
    print(f"{'='*50}")
    print(f"  난이도: {difficulty} | 스탯 총합: {stat_pool} | 범위: {min_stat}~{max_stat}")
    print(f"  파티 인원: {min_party}~{max_party}명 (권장: {rec_party}명)")
    print(f"  사용 가능 클래스: {', '.join(available_classes)}")

    # 기본 파티 표시
    print(f"\n--- 기본 파티 ({len(party)}명) ---")
    for i, p in enumerate(party):
        cls_name = p["class"]
        hp, mp = calculate_hp_mp(p, classes)
        ctrl = "USER" if p.get("controlled_by") == "user" else "AI"
        stats_str = " ".join(f"{k}:{v}" for k, v in p["stats"].items())
        pool_name = auto_names.get(cls_name, ["?"])
        default_name = pool_name[0] if pool_name else "?"
        name_display = p.get("name") or default_name
        print(f"  [{i+1}] {name_display} ({cls_name}) [{ctrl}]")
        print(f"      {stats_str} | HP:{hp} MP:{mp}")
        print(f"      장비: {', '.join(p.get('starting_inventory', []))}")
    print(f"{'─'*40}")

    # 수락 / 커스텀 선택 (명시적 선택 필수 — 빈칸 자동 수락 금지)
    print(f"\n  [1] 기본 파티로 시작 (이름만 변경 가능)")
    print(f"  [2] 커스텀 (이름/클래스/스탯 변경)")
    choice = ""
    for _ in range(20):  # 최대 20회 재시도
        try:
            choice = input(f"\n선택 (1 또는 2): ").strip()
        except EOFError:
            print("  [WARN] 입력 종료 — 캐릭터 메이킹을 건너뜁니다.")
            choice = "1"  # EOF 시 기본 파티로 폴백 (이름 확인은 아래에서)
            break
        if choice in ("1", "2"):
            break
        print("  ※ 1 또는 2를 입력해주세요.")

    if choice == "2":
        players = _custom_character_making(party, classes, stat_pool, min_stat, max_stat,
                                           available_classes, auto_names)
    else:
        # 기본 파티 수락 — 각 캐릭터 이름을 반드시 확인
        print(f"\n--- 기본 파티 이름 설정 ---")
        players = []
        eof_reached = False
        for p in party:
            cls_name = p["class"]
            ctrl = "USER" if p.get("controlled_by") == "user" else "AI"
            pool = auto_names.get(cls_name, ["모험가"])
            default_name = pool[0] if pool else "모험가"
            if eof_reached:
                name = default_name
                print(f"  [{cls_name}/{ctrl}] -> {name} (자동)")
            else:
                name = default_name
                for _ in range(10):
                    try:
                        raw = input(f"  [{cls_name}/{ctrl}] 이름 (빈칸={default_name}): ").strip()
                    except EOFError:
                        eof_reached = True
                        break
                    candidate = raw if raw else default_name
                    try:
                        confirm = input(f"    '{candidate}'(으)로 확정? (Y/n): ").strip().lower()
                    except EOFError:
                        eof_reached = True
                        name = candidate
                        break
                    if confirm in ("", "y", "yes"):
                        name = candidate
                        print(f"    -> {name}")
                        break
                    print(f"    다시 입력해주세요.")
                else:
                    name = default_name
                if eof_reached:
                    print(f"  [{cls_name}/{ctrl}] -> {name} (EOF)")

            hp, mp = calculate_hp_mp(p, classes)
            player = _build_player(p, name, cls_name, hp, mp)
            players.append(player)

    # 파티 인원 검증
    if len(players) < min_party or len(players) > max_party:
        print(f"\n[경고] 파티 인원이 범위를 벗어났습니다: {len(players)}명 (허용: {min_party}~{max_party}명)")
        print(f"  시나리오가 {rec_party}명에 맞춰 설계되어 밸런스가 맞지 않을 수 있습니다.")

    # 최종 확인
    print(f"\n--- 최종 파티 ({len(players)}명) ---")
    for p in players:
        ctrl = "USER" if p["controlled_by"] == "user" else "AI"
        stats_str = " ".join(f"{k}:{v}" for k, v in p["stats"].items())
        print(f"  {p['name']} ({p['class']}) [{ctrl}] HP:{p['hp']}/{p['max_hp']} MP:{p['mp']}/{p['max_mp']}")
        print(f"    {stats_str}")
    print()

    return players


def _custom_character_making(party, classes, stat_pool, min_stat, max_stat,
                              available_classes, auto_names):
    """커스텀 캐릭터 메이킹. 각 캐릭터의 이름, 클래스, 스탯을 변경 가능."""
    class_data = classes.get("classes", {})
    players = []

    for i, p in enumerate(party):
        print(f"\n--- 캐릭터 {i+1}/{len(party)} ---")
        ctrl = "USER" if p.get("controlled_by") == "user" else "AI"
        print(f"  조종: [{ctrl}]")

        # 클래스 선택
        current_cls = p["class"]
        print(f"  현재 클래스: {current_cls}")
        for j, cls_name in enumerate(available_classes, 1):
            cd = class_data[cls_name]
            marker = " (현재)" if cls_name == current_cls else ""
            print(f"    [{j}] {cls_name} — {cd['role']}{marker}")
        try:
            cls_choice = input(f"  클래스 선택 (빈칸={current_cls}): ").strip()
        except EOFError:
            cls_choice = ""
        if cls_choice and cls_choice.isdigit():
            idx = int(cls_choice) - 1
            if 0 <= idx < len(available_classes):
                current_cls = available_classes[idx]
        print(f"    -> {current_cls}")

        # 이름 입력 (확인 필수)
        pool = auto_names.get(current_cls, ["모험가"])
        default_name = pool[0] if pool else "모험가"
        name = default_name
        for _ in range(10):
            try:
                raw = input(f"  이름 (빈칸={default_name}): ").strip()
            except EOFError:
                break
            candidate = raw if raw else default_name
            try:
                confirm = input(f"    '{candidate}'(으)로 확정? (Y/n): ").strip().lower()
            except EOFError:
                name = candidate
                break
            if confirm in ("", "y", "yes"):
                name = candidate
                print(f"    -> {name}")
                break
            print(f"    다시 입력해주세요.")

        # 스탯 배분
        recommended = class_data.get(current_cls, {}).get("recommended_stats", p["stats"])
        print(f"  스탯 배분 (총합 {stat_pool}, 범위 {min_stat}~{max_stat})")
        print(f"  추천: {' '.join(f'{k}:{v}' for k, v in recommended.items())}")
        print(f"  [1] 추천 스탯 사용")
        print(f"  [2] 직접 입력")
        try:
            stat_choice = input(f"  선택 (빈칸=추천): ").strip()
        except EOFError:
            stat_choice = ""

        if stat_choice == "2":
            stats = _input_stats(stat_pool, min_stat, max_stat)
        else:
            stats = dict(recommended)
        print(f"    -> {' '.join(f'{k}:{v}' for k, v in stats.items())} (합계:{sum(stats.values())})")

        # HP/MP 계산
        temp_p = dict(p)
        temp_p["class"] = current_cls
        temp_p["stats"] = stats
        hp, mp = calculate_hp_mp(temp_p, classes)
        player = _build_player(p, name, current_cls, hp, mp, stats=stats)
        players.append(player)
        print(f"  [OK] {name} ({current_cls}) HP:{hp} MP:{mp}")

    return players


def _input_stats(stat_pool, min_stat, max_stat):
    """유저가 직접 스탯을 입력. 합계가 stat_pool이 될 때까지 반복."""
    stat_names = ["STR", "DEX", "INT", "CON"]
    while True:
        stats = {}
        remaining = stat_pool
        for j, stat in enumerate(stat_names):
            is_last = (j == len(stat_names) - 1)
            if is_last:
                # 마지막 스탯은 남은 포인트 자동 배분
                val = remaining
                if val < min_stat or val > max_stat:
                    print(f"    [!] 남은 포인트({remaining})가 범위({min_stat}~{max_stat}) 밖입니다. 다시 입력하세요.")
                    break
                stats[stat] = val
                remaining = 0
                print(f"    {stat}: {val} (자동 배분)")
            else:
                try:
                    raw = input(f"    {stat} ({min_stat}~{max_stat}, 남은:{remaining}): ").strip()
                except EOFError:
                    raw = ""
                if not raw:
                    val = min_stat
                else:
                    try:
                        val = int(raw)
                    except ValueError:
                        val = min_stat
                val = max(min_stat, min(max_stat, val))
                # 남은 포인트로 나머지 스탯이 최소값 이상이 되는지 확인
                slots_left = len(stat_names) - j - 1
                if remaining - val < min_stat * slots_left:
                    val = remaining - min_stat * slots_left
                    print(f"    [!] 나머지 스탯 최소값 보장을 위해 {stat}={val}로 조정")
                stats[stat] = val
                remaining -= val
                print(f"    {stat}: {val}")
        else:
            # for문이 break 없이 완료
            total = sum(stats.values())
            if total == stat_pool:
                return stats
            print(f"    [!] 합계 {total} ≠ {stat_pool}. 다시 입력하세요.")
            continue
        # break로 빠져나온 경우 — 다시 시도
        print(f"    다시 입력합니다...")
        continue


def _build_player(template, name, cls_name, hp, mp, stats=None):
    """플레이어 딕셔너리 생성.
    template: 시나리오 default_party의 플레이어 또는 외부 주입 데이터.
    agent_id, background 등 추가 필드가 있으면 그대로 포함."""
    player = {
        "id": template["id"],
        "name": name,
        "class": cls_name,
        "level": template.get("level", 1),
        "xp": template.get("xp", 0),
        "hp": hp,
        "max_hp": hp,
        "mp": mp,
        "max_mp": mp,
        "stats": stats or template["stats"],
        "position": [0, 0],
        "status_effects": [],
        "inventory": template.get("starting_inventory", template.get("inventory", [])),
        "available_actions": template.get("available_actions", []),
        "controlled_by": template.get("controlled_by", "ai"),
        "race": template.get("race", "인간"),
        "appearance": template.get("appearance", {}),
    }
    # 선택적 확장 필드 (에이전트 시스템, 배경 등)
    if template.get("agent_id"):
        player["agent_id"] = template["agent_id"]
    if template.get("background"):
        player["background"] = template["background"]
    return player


def _build_party_from_data(party_data, scenario, classes):
    """외부 주입 파티 데이터를 정규화하여 플레이어 리스트 생성.
    CLI 대화형 캐릭터 메이킹과 동일한 결과물을 만든다.

    party_data: [{"id":1, "name":"가온", "class":"전사", "stats":{...}, ...}, ...]
    scenario: scenario.json 데이터 (default_party에서 템플릿 참조)
    classes: character_classes.json 데이터 (HP/MP 계산용)

    HP/MP가 이미 있으면 그대로 사용, 없으면 calculate_hp_mp로 자동 계산.
    인벤토리가 없으면 해당 클래스의 starting_equipment 사용.
    """
    cls_data = classes.get("classes", {})

    players = []
    for p in party_data:
        cls_name = p["class"]
        cls_info = cls_data.get(cls_name, {})

        # 스탯: 외부 데이터 필수, 없으면 클래스 권장값
        stats = p.get("stats", cls_info.get("recommended_stats", {"STR": 10, "DEX": 10, "INT": 10, "CON": 10}))

        # HP/MP: 이미 있으면 사용, 없으면 클래스 공식으로 자동 계산
        if "hp" in p and "mp" in p:
            hp, mp = p["hp"], p["mp"]
        else:
            hp, mp = calculate_hp_mp({"class": cls_name, "stats": stats}, classes)

        # 인벤토리: 외부 데이터 → 클래스 starting_equipment → 빈 리스트
        if "inventory" not in p and "starting_inventory" not in p:
            p["starting_inventory"] = cls_info.get("starting_equipment", [])

        # available_actions: 외부 데이터 → 클래스 기본값
        if "available_actions" not in p:
            p["available_actions"] = cls_info.get("available_actions", [])

        player = _build_player(p, p["name"], cls_name, hp, mp, stats)
        players.append(player)

    return players


def _carry_over_npc_states(new_scenario_id, from_scenario, prev_save, new_state):
    """이전 시나리오의 세계관 NPC 상태를 새 시나리오로 이월 (시간 연속성).
    - 이전에서 dead인 세계관 NPC → 새 시나리오에서도 dead
    - memory, relationships 등 축적 데이터 이월
    - monster는 이월 안 함 (시나리오별 독립)
    """
    prev_gs = prev_save.get("game_state", {})
    prev_npcs = {n["name"]: n for n in prev_gs.get("npcs", []) if n.get("type") != "monster"}

    # 이전 시나리오의 NPC 엔티티 파일에서 상세 데이터 수집
    prev_ent_dir = os.path.join(BASE_DIR, "entities", from_scenario, "npcs")
    prev_entities = {}  # name → entity data
    if os.path.isdir(prev_ent_dir):
        for fname in os.listdir(prev_ent_dir):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(prev_ent_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    ent = json.load(f)
                if ent.get("type") != "monster":
                    prev_entities[ent.get("name", "")] = ent
            except (json.JSONDecodeError, KeyError):
                pass

    if not prev_npcs and not prev_entities:
        return

    # 새 시나리오의 NPC에 이전 상태 적용
    new_ent_dir = os.path.join(BASE_DIR, "entities", new_scenario_id, "npcs")
    carried = []
    dead_npcs = []

    for npc_name, prev_npc in prev_npcs.items():
        prev_status = prev_npc.get("status", "alive")
        prev_entity = prev_entities.get(npc_name, {})

        # 새 시나리오의 game_state.npcs에서 같은 이름의 NPC 찾기
        new_npc = next((n for n in new_state.get("npcs", []) if n["name"] == npc_name), None)

        if prev_status in ("dead", "removed"):
            if new_npc:
                # 이전에서 죽은 NPC가 새 시나리오에 등록됨 → dead로 변경
                new_npc["status"] = "dead"
                dead_npcs.append(npc_name)
            # 새 시나리오에 없으면 무시 (등장 예정 아님)
            continue

        # 살아있는 세계관 NPC → 엔티티에 memory/relationships 이월
        if prev_entity:
            new_ent_path = os.path.join(new_ent_dir, f"npc_{prev_entity['id']}.json")
            # 새 시나리오에도 같은 ID의 엔티티가 있으면 이월
            if os.path.exists(new_ent_path):
                try:
                    with open(new_ent_path, "r", encoding="utf-8") as f:
                        new_entity = json.load(f)
                    # 축적 데이터 이월 (memory, relationships, personality는 보존)
                    if prev_entity.get("memory"):
                        new_entity["memory"] = prev_entity["memory"]
                    if prev_entity.get("relationships"):
                        new_entity["relationships"] = prev_entity["relationships"]
                    new_entity["status"] = prev_status
                    save_json(new_ent_path, new_entity)
                    carried.append(npc_name)
                except (json.JSONDecodeError, KeyError):
                    pass
            else:
                # 같은 ID가 없지만 같은 이름의 엔티티가 있을 수 있음 → 이름으로 탐색
                for fname in os.listdir(new_ent_dir) if os.path.isdir(new_ent_dir) else []:
                    if not fname.endswith(".json"):
                        continue
                    try:
                        fpath = os.path.join(new_ent_dir, fname)
                        with open(fpath, "r", encoding="utf-8") as f:
                            ne = json.load(f)
                        if ne.get("name") == npc_name:
                            if prev_entity.get("memory"):
                                ne["memory"] = prev_entity["memory"]
                            if prev_entity.get("relationships"):
                                ne["relationships"] = prev_entity["relationships"]
                            ne["status"] = prev_status
                            save_json(fpath, ne)
                            carried.append(npc_name)
                            break
                    except (json.JSONDecodeError, KeyError):
                        pass

    # game_state 저장 (dead NPC 반영)
    if dead_npcs:
        save_json("data/game_state.json", new_state)

    if carried:
        print(f"  [OK] NPC 상태 이월: {', '.join(carried)}")
    if dead_npcs:
        print(f"  [WARN] 이전 시나리오에서 사망한 NPC: {', '.join(dead_npcs)} → dead 상태로 등록")


def _activate_worldbuilding(scenario_entry):
    """시나리오의 세계관 파일을 data/worldbuilding.json에 복사."""
    wb_id = scenario_entry.get("worldbuilding")
    if not wb_id:
        print(f"  [INFO] worldbuilding 미지정 — 기존 data/worldbuilding.json 유지")
        return

    # worldbuildings/index.json에서 파일 경로 찾기
    wb_index_path = os.path.join(BASE_DIR, "worldbuildings", "index.json")
    if os.path.exists(wb_index_path):
        wb_index = load_json(wb_index_path)
        wb_entry = next((w for w in wb_index.get("worldbuildings", []) if w["id"] == wb_id), None)
        if wb_entry:
            wb_file = wb_entry["file"]
        else:
            wb_file = f"worldbuildings/{wb_id}.json"
    else:
        wb_file = f"worldbuildings/{wb_id}.json"

    wb_src = os.path.join(BASE_DIR, wb_file)
    wb_dst = os.path.join(BASE_DIR, "data", "worldbuilding.json")

    if os.path.exists(wb_src):
        if os.path.abspath(wb_src) != os.path.abspath(wb_dst):
            shutil.copy2(wb_src, wb_dst)
            print(f"  [OK] data/worldbuilding.json <- {wb_file}")
    else:
        print(f"  [WARN] 세계관 파일 없음: {wb_file}")


def _try_restore_scene():
    """Flask 서버가 실행 중이면 restore_scene API 호출."""
    try:
        import urllib.request
        req = urllib.request.Request("http://localhost:5000/api/game-state", method="GET")
        urllib.request.urlopen(req, timeout=2)
        print(f"  [OK] Flask 서버 감지됨 (localhost:5000)")
        # restore_scene은 Flask 서버 내부에서 동작하므로 직접 호출 불가
        # 대신 load API를 통해 간접 트리거하거나, 유저에게 안내
        print(f"  [INFO] 웹 UI 장면 복원: Flask 서버 재시작 또는 브라우저 새로고침 필요")
    except Exception:
        print(f"  [INFO] Flask 서버 미실행. start_server.bat 또는 SD venv Python app.py 실행 시 자동 복원됩니다.")


def _print_state_summary(state):
    """현재 상태 요약 출력."""
    print(f"\n--- 상태 요약 ---")
    info = state.get("game_info", {})
    print(f"  시나리오: {info.get('title', '?')} ({info.get('scenario_id', '?')})")
    print(f"  챕터: {info.get('current_chapter', '?')} | 턴: {state.get('turn_count', 0)} | 상태: {info.get('status', '?')}")
    print(f"  위치: {state.get('current_location', '?')}")
    print(f"  파티:")
    for p in state.get("players", []):
        ctrl = "USER" if p.get("controlled_by") == "user" else "AI"
        print(f"    {p['name']} ({p['class']}) Lv.{p.get('level',1)} HP:{p['hp']}/{p['max_hp']} MP:{p['mp']}/{p['max_mp']} [{ctrl}]")
    npcs_alive = [n for n in state.get("npcs", []) if n.get("status") not in ("dead", "removed")]
    if npcs_alive:
        print(f"  NPC ({len(npcs_alive)}명): {', '.join(n['name'] for n in npcs_alive)}")
    print(f"-----------------\n")


def _start_mode_select(scenario_id, scenario):
    """시작 모드 선택: 새 게임 / 세이브 로드. 'new' 또는 'load' 반환."""
    print(f"\n=== 시작 모드 ===")
    save_dir = os.path.join(BASE_DIR, "saves", scenario_id)
    save_slots = []
    if os.path.exists(save_dir):
        for slot_name in sorted(os.listdir(save_dir)):
            slot_path = os.path.join(save_dir, slot_name, "save.json")
            if os.path.exists(slot_path):
                try:
                    save_data = load_json(slot_path)
                except Exception:
                    save_data = None
                if save_data:
                    info = save_data.get("save_info", {})
                    save_slots.append({
                        "slot": slot_name,
                        "description": info.get("description", ""),
                        "turn": info.get("turn_count", 0),
                        "chapter": info.get("chapter", ""),
                        "saved_at": info.get("saved_at", ""),
                    })

    if save_slots:
        rec_level = scenario.get("scenario_info", {}).get("recommended_level", 1)
        print(f"  [1] 새 게임 — 레벨 {rec_level} 캐릭터로 처음부터")
        print()
        print(f"  --- 세이브 파일 ---")
        for i, sv in enumerate(save_slots, 2):
            slot_num = sv['slot'].replace('slot_', '#')
            desc = sv['description'] or "(설명 없음)"
            chapter = f"Ch.{sv.get('chapter', '?')}" if sv.get('chapter') else ""
            print(f"  [{i}] 슬롯{slot_num}  {desc}  턴 {sv['turn']}  {chapter}  {sv['saved_at']}")
        try:
            mode_choice = input(f"\n선택 (빈칸=새 게임): ").strip()
            if mode_choice and int(mode_choice) >= 2:
                slot_idx = int(mode_choice) - 2
                if 0 <= slot_idx < len(save_slots):
                    sv = save_slots[slot_idx]
                    slot_num = int(sv['slot'].replace('slot_', ''))
                    save_file = os.path.join("saves", scenario_id, sv['slot'], "save.json")
                    print(f"\n=== 세이브 로드 ===")
                    print(f"  시나리오: {scenario_id}")
                    print(f"  슬롯: {slot_num} ({sv['slot']})")
                    print(f"  파일: {save_file}")
                    print(f"  설명: {sv['description']}")
                    print(f"  저장일: {sv['saved_at']}")
                    from core.save_manager import SaveManager
                    sm = SaveManager()
                    save_info = sm.load_game(scenario_id, slot_num)
                    if save_info:
                        print(f"  -> 로드 완료!")
                        state = load_json("data/game_state.json")
                        _print_state_summary(state)
                    else:
                        print(f"  [ERROR] 세이브 로드 실패")
                    return "load"
        except (ValueError, IndexError, EOFError):
            pass
        print(f"  -> 새 게임으로 시작합니다.")
    else:
        print(f"  저장된 게임 없음 — 새 게임으로 시작합니다.")
    return "new"


# ─── 메인 ───

def main():
    if len(sys.argv) < 2:
        # 대화형 모드
        # 기존 세이브 파일 표시
        _show_existing_saves()
        scenarios = list_scenarios()
        choice = input("\n시나리오 번호 선택 (0=취소, L=세이브 로드): ").strip()
        if choice.lower() == "l":
            load_game()
            return
        try:
            idx = int(choice) - 1
            if idx < 0:
                print("취소됨.")
                return
            scenario = scenarios[idx]
        except (ValueError, IndexError):
            print("잘못된 선택입니다.")
            return

        # 시작 모드 결정 — 룰셋 선택은 new_game 내부에서 처리
        has_prereq = bool(scenario.get("prerequisite"))
        prereq_required = scenario.get("prerequisite_required", False)

        if has_prereq and prereq_required:
            # 이어하기만 가능
            print(f"\n이 시나리오는 '{scenario['prerequisite']}' 클리어 필수입니다.")
            continue_game(scenario["id"], scenario["prerequisite"])
        elif has_prereq and not prereq_required:
            # 이어하기 옵션 추가 표시
            print(f"\n선행 시나리오: {scenario['prerequisite']} (이어하기 가능)")
            print(f"  [1] 새 게임")
            print(f"  [2] 이어하기 (선행 시나리오 세이브에서)")
            try:
                mode = input("선택 (빈칸=새 게임): ").strip()
            except EOFError:
                mode = ""
            if mode == "2":
                continue_game(scenario["id"], scenario["prerequisite"])
            else:
                new_game(scenario["id"])
        else:
            # 선행 없음 — new_game 내부에서 시작 모드(새 게임/세이브 로드) 처리
            new_game(scenario["id"])

    elif sys.argv[1] == "new":
        if len(sys.argv) < 3:
            print("Usage: python game_start.py new <scenario_id>")
            return
        new_game(sys.argv[2])

    elif sys.argv[1] == "continue":
        if len(sys.argv) < 3:
            print("Usage: python game_start.py continue <scenario_id> --from <prev_scenario_id>")
            return
        scenario_id = sys.argv[2]

        # --from 파싱
        from_id = None
        if "--from" in sys.argv:
            from_idx = sys.argv.index("--from")
            if from_idx + 1 < len(sys.argv):
                from_id = sys.argv[from_idx + 1]

        # --from 없으면 시나리오의 prerequisite에서 자동 추출
        if not from_id:
            index = load_json("scenarios/index.json")
            entry = next((s for s in index["scenarios"] if s["id"] == scenario_id), {})
            from_id = entry.get("prerequisite")

        if from_id:
            continue_game(scenario_id, from_id)
        else:
            print(f"[ERROR] 이어할 시나리오를 지정하세요: --from <prev_scenario_id>")

    elif sys.argv[1] == "load":
        load_game()

    else:
        print("Usage: python game_start.py [new|continue|load] [scenario_id] [--from prev_id]")
        print()
        print("  (인자 없음)     대화형 모드: 시나리오 선택 + 시작 모드 선택")
        print("  new <id>        특정 시나리오로 새 게임")
        print("  continue <id>   이전 시나리오에서 이어하기")
        print("    --from <id>   이전 시나리오 ID (생략 시 prerequisite 자동 사용)")
        print("  load            세이브 목록에서 선택하여 로드")


if __name__ == "__main__":
    main()
