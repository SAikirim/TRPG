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
    """시나리오용 엔티티 디렉토리와 파일을 생성."""
    ent_dir = os.path.join(BASE_DIR, "entities", scenario_id)
    for sub in ["players", "npcs", "objects"]:
        os.makedirs(os.path.join(ent_dir, sub), exist_ok=True)

    # 플레이어 엔티티
    for p in players:
        entity = {
            "id": p["id"],
            "name": p["name"],
            "class": p["class"],
            "level": p.get("level", 1),
            "background": {"origin": "", "motivation": "", "personality": ""},
            "stats": p.get("stats", {}),
            "hp": p.get("hp", p.get("max_hp", 10)),
            "max_hp": p.get("max_hp", 10),
            "mp": p.get("mp", p.get("max_mp", 5)),
            "max_mp": p.get("max_mp", 5),
            "position": p.get("position", [0, 0]),
            "status_effects": [],
            "inventory": p.get("inventory", []),
            "equipment": {},
            "available_actions": [],
            "combat_state": {"is_in_combat": False, "defense_bonus": 0, "next_turn_penalty": 0},
            "history": {
                "actions_taken": [], "damage_dealt_total": 0, "damage_received_total": 0,
                "kills": [], "items_used": [], "turns_played": 0
            },
            "conditions": {"alive": True, "conscious": True, "death_save_turns": 0},
            "controlled_by": p.get("controlled_by", "agent"),
        }
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

        save_json(f"entities/{scenario_id}/npcs/npc_{n['id']}.json", entity)

    print(f"  엔티티 생성 완료: players={len(players)}, npcs={len(npcs)}")


# ─── 새 게임 ───

def new_game(scenario_id):
    """새 게임 시작. 시나리오 로드 → 캐릭터 메이킹 → 상태 초기화 → 엔티티 생성."""
    index = load_json("scenarios/index.json")
    scenario_entry = next((s for s in index["scenarios"] if s["id"] == scenario_id), None)
    if not scenario_entry:
        print(f"[ERROR] 시나리오 '{scenario_id}'를 찾을 수 없습니다.")
        print(f"  등록된 시나리오: {[s['id'] for s in index['scenarios']]}")
        return False

    # 시나리오 파일 로드
    scenario_file = scenario_entry.get("scenario_file", f"scenarios/{scenario_id}.json")
    # scenario_file이 scenarios/ 접두사 없이 있을 수 있음
    if not os.path.exists(os.path.join(BASE_DIR, scenario_file)):
        alt = f"scenarios/{scenario_file}"
        if os.path.exists(os.path.join(BASE_DIR, alt)):
            scenario_file = alt
    scenario = load_json(scenario_file)

    # initial_state 로드
    initial_file = scenario_entry.get("initial_state", "game_state_initial.json")
    if not os.path.exists(os.path.join(BASE_DIR, initial_file)):
        # 폴백: 루트의 game_state_initial.json
        initial_file = "game_state_initial.json"
    if not os.path.exists(os.path.join(BASE_DIR, initial_file)):
        print(f"[ERROR] initial_state 파일을 찾을 수 없습니다: {initial_file}")
        return False
    state = load_json(initial_file)

    # 클래스 데이터 로드
    classes = load_json("templates/character_classes.json")

    # 파티 구성
    party = scenario.get("default_party", {}).get("players", [])
    print(f"\n=== 캐릭터 메이킹: {scenario['scenario_info']['title']} ===")
    print(f"기본 파티 ({len(party)}명):\n")

    players = []
    for p in party:
        cls_name = p["class"]
        name = p.get("name", "")

        # 이름이 비어있으면 유저에게 입력 요청
        if not name:
            auto_names = classes.get("auto_generate", {}).get("name_pool", {})
            pool = auto_names.get(cls_name, ["모험가"])
            default_name = pool[0] if pool else "모험가"
            name = input(f"  [{cls_name}] 이름 입력 (빈칸={default_name}): ").strip()
            if not name:
                name = default_name
                print(f"    -> 자동 이름: {name}")

        hp, mp = calculate_hp_mp(p, classes)
        player = {
            "id": p["id"],
            "name": name,
            "class": cls_name,
            "level": p.get("level", 1),
            "xp": p.get("xp", 0),
            "hp": hp,
            "max_hp": hp,
            "mp": mp,
            "max_mp": mp,
            "stats": p["stats"],
            "position": [0, 0],
            "status_effects": [],
            "inventory": p.get("starting_inventory", []),
            "controlled_by": p.get("controlled_by", "agent"),
        }
        players.append(player)
        ctrl = "USER" if player["controlled_by"] == "user" else "AI"
        print(f"  [OK] {name} ({cls_name}) HP:{hp} MP:{mp} [{ctrl}]")

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
    save_json("game_state.json", state)
    print(f"\n  [OK] game_state.json 저장 완료")

    # 엔티티 생성
    create_entities(scenario_id, players, npcs)

    # current_session.json 갱신
    chapter_name = scenario["chapters"][0]["name"] if scenario.get("chapters") else ""
    session = {
        "active_scenario": scenario_id,
        "active_save_slot": 1,
        "ruleset": scenario["scenario_info"].get("ruleset", scenario_entry.get("ruleset", "fantasy_basic")),
        "turn": 0,
        "chapter": 1,
        "chapter_name": chapter_name,
        "status": "active",
        "party_summary": [
            {
                "name": p["name"], "class": p["class"],
                "hp": f"{p['hp']}/{p['max_hp']}", "mp": f"{p['mp']}/{p['max_mp']}",
                "key_items": p.get("inventory", [])[:5]
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
    save_json("current_session.json", session)
    print(f"  [OK] current_session.json 저장 완료")

    # 활성 시나리오/룰셋 파일 복사 (scenario.json, rules.json)
    _activate_scenario_files(scenario_entry, scenario_file)

    # 맵 생성
    try:
        from map_generator import MapGenerator
        MapGenerator().save_map()
        print(f"  [OK] 맵 생성 완료")
    except Exception as e:
        print(f"  [WARN] 맵 생성 실패 (수동 실행 필요): {e}")

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
    print(f"Flask 서버: python app.py -> http://localhost:5000")
    _print_state_summary(state)
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
    state = load_json("game_state.json")
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
                    "controlled_by": prev_p.get("controlled_by", "agent"),
                })
                break
    save_json("game_state.json", state)

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
                "controlled_by": p.get("controlled_by", "agent"),
            })
            save_json(ent_path, ent)

    # current_session 파티 요약 갱신
    session = load_json("current_session.json")
    session["party_summary"] = [
        {
            "name": p["name"], "class": p["class"],
            "hp": f"{p['hp']}/{p['max_hp']}", "mp": f"{p['mp']}/{p['max_mp']}",
            "key_items": p.get("inventory", [])[:5]
        }
        for p in state["players"]
    ]
    session["progress_notes"].insert(0, f"'{from_scenario}' 에서 캐릭터 이어받기 완료")
    save_json("current_session.json", session)

    print(f"\n  [OK] '{from_scenario}' 에서 캐릭터 데이터 이어받기 완료")
    _print_state_summary(state)
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
        print(f"  [{i+1}] {s['scenario_id']}/{s['slot']}: 턴{info.get('turn_count', '?')} - {info.get('description', '')} ({info.get('saved_at', '')})")

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
    save_json("game_state.json", save_data["game_state"])
    print(f"\n  [OK] 세이브 로드 완료: {selected['scenario_id']}/{selected['slot']}")

    # 맵 갱신
    try:
        from map_generator import MapGenerator
        MapGenerator().save_map()
        print(f"  [OK] 맵 갱신 완료")
    except Exception as e:
        print(f"  [WARN] 맵 갱신 실패: {e}")

    # 장면 복원
    _try_restore_scene()

    _print_state_summary(save_data["game_state"])
    return True


# ─── 유틸리티 ───

def _activate_scenario_files(scenario_entry, scenario_file):
    """활성 시나리오/룰셋 파일을 루트에 복사 (scenario.json, rules.json)."""
    # scenario.json
    src = os.path.join(BASE_DIR, scenario_file)
    dst = os.path.join(BASE_DIR, "scenario.json")
    if os.path.exists(src) and os.path.abspath(src) != os.path.abspath(dst):
        shutil.copy2(src, dst)
        print(f"  [OK] scenario.json <- {scenario_file}")

    # rules.json (룰셋)
    ruleset_id = scenario_entry.get("ruleset", "fantasy_basic")
    ruleset_file = f"rulesets/{ruleset_id}.json"
    ruleset_src = os.path.join(BASE_DIR, ruleset_file)
    rules_dst = os.path.join(BASE_DIR, "rules.json")
    if os.path.exists(ruleset_src):
        shutil.copy2(ruleset_src, rules_dst)
        print(f"  [OK] rules.json <- {ruleset_file}")


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
        print(f"  [INFO] Flask 서버 미실행. 나중에 python app.py 실행 시 자동 복원됩니다.")


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


# ─── 메인 ───

def main():
    if len(sys.argv) < 2:
        # 대화형 모드
        scenarios = list_scenarios()
        choice = input("\n시나리오 번호 선택 (0=취소): ").strip()
        try:
            idx = int(choice) - 1
            if idx < 0:
                print("취소됨.")
                return
            scenario = scenarios[idx]
        except (ValueError, IndexError):
            print("잘못된 선택입니다.")
            return

        # 시작 모드 결정
        has_prereq = bool(scenario.get("prerequisite"))
        prereq_required = scenario.get("prerequisite_required", False)

        if has_prereq and prereq_required:
            # 이어하기만 가능
            print(f"\n이 시나리오는 '{scenario['prerequisite']}' 클리어 필수입니다.")
            continue_game(scenario["id"], scenario["prerequisite"])
        elif has_prereq and not prereq_required:
            # 선택 가능
            print(f"\n선행 시나리오: {scenario['prerequisite']}")
            mode = input("시작 모드 [1: 새 게임 / 2: 이어하기 / 3: 세이브 로드]: ").strip()
            if mode == "2":
                continue_game(scenario["id"], scenario["prerequisite"])
            elif mode == "3":
                load_game()
            else:
                new_game(scenario["id"])
        else:
            # 선행 없음 — 새 게임만
            mode = input("시작 모드 [1: 새 게임 / 3: 세이브 로드]: ").strip()
            if mode == "3":
                load_game()
            else:
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
