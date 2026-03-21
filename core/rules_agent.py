"""
룰 에이전트 보조 도구
- gm-update 시 자동 검증 (check_and_warn)
- Agent 툴에서 상세 검증 시 CLI 호출

자동 감지 항목:
  - HP 0 이하인데 alive 상태인 캐릭터
  - MP가 음수인 캐릭터
  - 상태이상 지속시간 만료 (tick 누락)
  - 장비 요구조건 미충족

사용법:
  python -m core.rules_agent check          전체 룰 정합성 검증
  python -m core.rules_agent check_combat   전투 상태 검증
  python -m core.rules_agent check_skills   스킬/MP 비용 검증
"""

import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME_STATE_PATH = os.path.join(BASE_DIR, "data", "game_state.json")
RULES_PATH = os.path.join(BASE_DIR, "data", "rules.json")
SKILLS_PATH = os.path.join(BASE_DIR, "data", "skills.json")
STATUS_EFFECTS_PATH = os.path.join(BASE_DIR, "data", "status_effects.json")


def _load_json(path):
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def check_and_warn(game_state=None, mechanics_results=None):
    """gm-update에서 호출되는 자동 검증. 경고를 문자열 리스트로 반환."""
    if game_state is None:
        game_state = _load_json(GAME_STATE_PATH)
    if game_state is None:
        return []

    warnings = []

    # 1. HP/MP 상태 정합성
    for p in game_state.get("players", []):
        name = p.get("name", f"player_{p.get('id')}")
        if p.get("hp", 1) <= 0 and "dead" not in str(p.get("status_effects", [])):
            warnings.append(f"⚖️ {name} HP={p['hp']} 이하인데 사망/기절 상태 아님")
        if p.get("mp", 0) < 0:
            warnings.append(f"⚖️ {name} MP={p['mp']} 음수 — 비용 초과 차감")
        if p.get("hp", 0) > p.get("max_hp", 999):
            warnings.append(f"⚖️ {name} HP={p['hp']} > max_hp={p['max_hp']}")
        if p.get("mp", 0) > p.get("max_mp", 999):
            warnings.append(f"⚖️ {name} MP={p['mp']} > max_mp={p['max_mp']}")

    # NPC도 동일 체크
    for n in game_state.get("npcs", []):
        name = n.get("name", f"npc_{n.get('id')}")
        if n.get("hp", 1) <= 0 and n.get("status") not in ("dead", "fled"):
            warnings.append(f"⚖️ NPC {name} HP={n['hp']} 이하인데 status={n.get('status')}")

    # 2. 상태이상 지속시간 체크
    for p in game_state.get("players", []):
        name = p.get("name", "")
        for effect in p.get("status_effects", []):
            if isinstance(effect, dict):
                remaining = effect.get("remaining_turns", -1)
                if remaining == 0:
                    warnings.append(
                        f"⚖️ {name}의 상태이상 '{effect.get('name', '?')}' "
                        f"지속시간 만료 — tick 처리 필요")

    # 3. mechanics_results 검증 (판정 결과가 있으면)
    if mechanics_results:
        for r in mechanics_results:
            if isinstance(r, dict) and r.get("error"):
                warnings.append(f"⚖️ 판정 오류: {r['error']}")

    return warnings


def check_full():
    """전체 룰 정합성 검증 (CLI용)."""
    state = _load_json(GAME_STATE_PATH)
    rules = _load_json(RULES_PATH)
    warnings = check_and_warn(state)

    # 장비 요구조건 체크
    if rules and state:
        equip_reqs = rules.get("combat", {}).get("equipment_properties", {}).get("requirements", {})
        scenario_id = state.get("game_info", {}).get("scenario_id", "")
        for p in state.get("players", []):
            ent_path = os.path.join(
                BASE_DIR, "entities", scenario_id, "players", f"player_{p['id']}.json")
            if not os.path.isfile(ent_path):
                continue
            entity = _load_json(ent_path)
            if not entity:
                continue
            equipment = entity.get("equipment", {})
            level = p.get("level", 1)
            for slot, item in equipment.items():
                if isinstance(item, dict):
                    req_level = item.get("required_level", 0)
                    if req_level > level:
                        warnings.append(
                            f"⚖️ {p['name']}의 {slot} '{item.get('name', '?')}' "
                            f"요구 레벨 {req_level} > 현재 레벨 {level}")

    return warnings


def main():
    if len(sys.argv) < 2:
        print("사용법: python -m core.rules_agent <check|check_combat|check_skills>")
        return

    cmd = sys.argv[1]

    if cmd == "check":
        warnings = check_full()
        if not warnings:
            print("✓ 룰 정합성 검증 통과")
        else:
            print(f"⚠ 문제 {len(warnings)}건:")
            for w in warnings:
                print(f"  {w}")

    elif cmd == "check_combat":
        state = _load_json(GAME_STATE_PATH)
        if state:
            warnings = [w for w in check_and_warn(state) if "HP" in w or "NPC" in w]
            if not warnings:
                print("✓ 전투 상태 정상")
            else:
                for w in warnings:
                    print(f"  {w}")

    elif cmd == "check_skills":
        state = _load_json(GAME_STATE_PATH)
        if state:
            warnings = [w for w in check_and_warn(state) if "MP" in w or "상태이상" in w]
            if not warnings:
                print("✓ 스킬/MP 상태 정상")
            else:
                for w in warnings:
                    print(f"  {w}")

    else:
        print(f"알 수 없는 명령: {cmd}")


if __name__ == "__main__":
    main()
