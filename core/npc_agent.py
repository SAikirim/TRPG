"""
NPC 에이전트 보조 도구
- gm-update 시 자동 검증 (check_and_warn)
- Agent 툴에서 NPC 대사/행동 생성 시 참조

자동 감지 항목:
  - game_state에 NPC가 있는데 엔티티 파일 없음
  - 엔티티 파일과 game_state의 상태 불일치
  - 같은 위치에 적대 NPC가 alive인데 전투 없이 진행

사용법:
  python -m core.npc_agent check              NPC 정합성 검증
  python -m core.npc_agent list               NPC 목록 + 상태
  python -m core.npc_agent info <npc_id>      NPC 상세 정보
"""

import json
import os
import sys
sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME_STATE_PATH = os.path.join(BASE_DIR, "data", "game_state.json")


def _load_json(path):
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _npc_dir(game_state):
    sid = game_state.get("game_info", {}).get("scenario_id", "default")
    return os.path.join(BASE_DIR, "entities", sid, "npcs")


def check_and_warn(game_state=None):
    """gm-update에서 호출되는 자동 검증. 경고를 문자열 리스트로 반환."""
    if game_state is None:
        game_state = _load_json(GAME_STATE_PATH)
    if game_state is None:
        return []

    warnings = []
    npc_dir = _npc_dir(game_state)

    # 플레이어 위치 (근접 판단용)
    player_positions = set()
    current_loc = game_state.get("current_location", "")
    for p in game_state.get("players", []):
        pos = p.get("position")
        if pos:
            player_positions.add(tuple(pos))

    for npc in game_state.get("npcs", []):
        npc_id = npc.get("id")
        npc_name = npc.get("name", f"npc_{npc_id}")

        # 1. 엔티티 파일 존재 여부
        entity_path = os.path.join(npc_dir, f"npc_{npc_id}.json")
        if not os.path.isfile(entity_path):
            warnings.append(
                f"💬 NPC '{npc_name}' (id:{npc_id}) 엔티티 파일 없음 — "
                f"python -m core.game_mechanics check_npcs 필요")
            continue

        # 2. 엔티티 ↔ game_state 상태 불일치
        entity = _load_json(entity_path)
        if entity:
            entity_status = entity.get("status", "")
            gs_status = npc.get("status", "")
            if entity_status and gs_status and entity_status != gs_status:
                warnings.append(
                    f"💬 NPC '{npc_name}' 상태 불일치 — "
                    f"game_state: {gs_status}, entity: {entity_status}")

            # HP 불일치
            entity_hp = entity.get("hp", entity.get("stats", {}).get("hp"))
            gs_hp = npc.get("hp")
            if entity_hp is not None and gs_hp is not None and entity_hp != gs_hp:
                warnings.append(
                    f"💬 NPC '{npc_name}' HP 불일치 — "
                    f"game_state: {gs_hp}, entity: {entity_hp}")

        # 3. 같은 위치의 적대 NPC alive 경고
        if npc.get("type") == "monster" and npc.get("status") in ("alive", "active"):
            npc_pos = npc.get("position")
            if npc_pos and tuple(npc_pos) in player_positions:
                warnings.append(
                    f"💬 적대 NPC '{npc_name}' 이 플레이어와 같은 위치 — "
                    f"전투 또는 조우 처리 필요")

    return warnings


def list_npcs():
    """NPC 목록 + 상태."""
    state = _load_json(GAME_STATE_PATH)
    if not state:
        return {"error": "game_state 없음"}

    npc_dir = _npc_dir(state)
    result = []
    for npc in state.get("npcs", []):
        npc_id = npc.get("id")
        entry = {
            "id": npc_id,
            "name": npc.get("name", "?"),
            "type": npc.get("type", "?"),
            "status": npc.get("status", "?"),
            "location": npc.get("location", "?"),
            "hp": npc.get("hp"),
            "has_entity": os.path.isfile(
                os.path.join(npc_dir, f"npc_{npc_id}.json")),
        }
        result.append(entry)
    return result


def npc_info(npc_id):
    """NPC 상세 정보 (game_state + entity 머지)."""
    state = _load_json(GAME_STATE_PATH)
    if not state:
        return {"error": "game_state 없음"}

    # game_state에서 찾기
    gs_npc = None
    for n in state.get("npcs", []):
        if n.get("id") == npc_id:
            gs_npc = n
            break
    if not gs_npc:
        return {"error": f"NPC {npc_id} 없음"}

    result = dict(gs_npc)

    # entity 머지
    npc_dir = _npc_dir(state)
    entity_path = os.path.join(npc_dir, f"npc_{npc_id}.json")
    if os.path.isfile(entity_path):
        entity = _load_json(entity_path)
        if entity:
            for key in ("personality", "memory", "relationships",
                        "behavior_pattern", "speech_style", "motivation"):
                if key in entity and key not in result:
                    result[key] = entity[key]
                elif key in entity.get("personality", {}):
                    result.setdefault("personality", {})[key] = entity["personality"][key]

    return result


def main():
    if len(sys.argv) < 2:
        print("사용법: python -m core.npc_agent <check|list|info> [args]")
        return

    cmd = sys.argv[1]

    if cmd == "check":
        warnings = check_and_warn()
        if not warnings:
            print("✓ NPC 정합성 검증 통과")
        else:
            print(f"⚠ 문제 {len(warnings)}건:")
            for w in warnings:
                print(f"  {w}")

    elif cmd == "list":
        npcs = list_npcs()
        if isinstance(npcs, dict) and "error" in npcs:
            print(npcs["error"])
        else:
            for n in npcs:
                icon = {"alive": "🟢", "dead": "💀", "fled": "🏃",
                        "active": "⚔️"}.get(n["status"], "❓")
                entity = "✓" if n["has_entity"] else "✗"
                print(f"  {icon} [{n['id']}] {n['name']} ({n['type']}) "
                      f"— {n['status']} entity:{entity}")

    elif cmd == "info" and len(sys.argv) >= 3:
        result = npc_info(int(sys.argv[2]))
        print(json.dumps(result, ensure_ascii=False, indent=2))

    else:
        print(f"알 수 없는 명령: {cmd}")


if __name__ == "__main__":
    main()
