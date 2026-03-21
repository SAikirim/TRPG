"""
시나리오 에이전트 보조 도구
- gm-update 시 자동 검증 (check_and_warn)
- Agent 툴에서 상세 분석 시 CLI 호출

자동 감지 항목:
  - 챕터 전환 조건 충족 여부
  - 퀘스트 완료 조건 도달 감지
  - 핵심 NPC 사망/이탈 시 스토리 영향
  - 시나리오 이탈 감지

사용법:
  python -m core.scenario_agent check           전체 시나리오 정합성
  python -m core.scenario_agent quests          퀘스트 상태 요약
  python -m core.scenario_agent chapter_info    현재 챕터 정보
"""

import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME_STATE_PATH = os.path.join(BASE_DIR, "data", "game_state.json")
SCENARIO_PATH = os.path.join(BASE_DIR, "data", "scenario.json")
QUESTS_PATH = os.path.join(BASE_DIR, "data", "quests.json")


def _load_json(path):
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def check_and_warn(game_state=None):
    """gm-update에서 호출되는 자동 검증. 경고를 문자열 리스트로 반환."""
    if game_state is None:
        game_state = _load_json(GAME_STATE_PATH)
    if game_state is None:
        return []

    scenario = _load_json(SCENARIO_PATH)
    quests = _load_json(QUESTS_PATH)
    warnings = []

    current_chapter = game_state.get("game_info", {}).get("current_chapter", 1)

    # 1. 퀘스트 상태 검증
    if quests:
        quest_data = quests.get("quests", {})
        # dict 형태 지원 (id: {...}) 및 list 형태 지원
        if isinstance(quest_data, dict):
            quest_list = list(quest_data.values())
        else:
            quest_list = quest_data

        active_quests = [q for q in quest_list
                         if isinstance(q, dict) and q.get("status") == "active"]
        for q in active_quests:
            q_name = q.get("title", q.get("name", "?"))

            # 완료 조건 체크 (아이템 기반)
            required_items = q.get("completion_items", [])
            if required_items:
                player_items = set()
                for p in game_state.get("players", []):
                    player_items.update(p.get("inventory", []))
                missing = [i for i in required_items if i not in player_items]
                if not missing:
                    warnings.append(
                        f"📜 퀘스트 '{q_name}' 완료 조건 충족 — "
                        f"status를 completed로 변경 필요")

            # 대상 NPC 사망 체크
            target_npc = q.get("target_npc")
            if target_npc:
                for n in game_state.get("npcs", []):
                    if n.get("name") == target_npc and n.get("status") == "dead":
                        warnings.append(
                            f"📜 퀘스트 '{q_name}' 대상 NPC '{target_npc}' 사망 — "
                            f"퀘스트 진행 불가, 실패 처리 또는 대체 경로 필요")

    # 2. 시나리오 챕터 전환 감지
    if scenario:
        chapters = scenario.get("chapters", [])
        current_ch = None
        for ch in chapters:
            if ch.get("id") == current_chapter:
                current_ch = ch
                break

        if current_ch:
            # 챕터 목표 달성 여부
            objectives = current_ch.get("objectives", [])
            for obj in objectives:
                if isinstance(obj, dict) and obj.get("type") == "reach_location":
                    target_loc = obj.get("location", "")
                    current_loc = game_state.get("current_location", "")
                    if target_loc and current_loc == target_loc:
                        warnings.append(
                            f"📜 챕터 {current_chapter} 목표 위치 '{target_loc}' 도달 — "
                            f"챕터 전환 검토 필요")

    # 3. 핵심 NPC 상태 체크
    if scenario:
        key_npcs = scenario.get("key_npcs", [])
        for npc_name in key_npcs:
            for n in game_state.get("npcs", []):
                if n.get("name") == npc_name:
                    if n.get("status") == "dead":
                        warnings.append(
                            f"📜 핵심 NPC '{npc_name}' 사망 — 스토리 분기 영향 검토 필요")
                    elif n.get("status") == "fled":
                        warnings.append(
                            f"📜 핵심 NPC '{npc_name}' 이탈 — 재등장 또는 대체 경로 필요")

    return warnings


def quest_summary():
    """퀘스트 상태 요약."""
    quests = _load_json(QUESTS_PATH)
    if not quests:
        return {"error": "quests.json 없음"}
    result = {"active": [], "completed": [], "failed": []}
    quest_data = quests.get("quests", {})
    if isinstance(quest_data, dict):
        quest_list = list(quest_data.values())
    else:
        quest_list = quest_data
    for q in quest_list:
        if not isinstance(q, dict):
            continue
        status = q.get("status", "unknown")
        entry = {"name": q.get("title", q.get("name", "?")),
                 "description": q.get("description", "")}
        if status == "active":
            result["active"].append(entry)
        elif status == "completed":
            result["completed"].append(entry)
        elif status == "failed":
            result["failed"].append(entry)
    return result


def chapter_info():
    """현재 챕터 정보."""
    state = _load_json(GAME_STATE_PATH)
    scenario = _load_json(SCENARIO_PATH)
    if not state or not scenario:
        return {"error": "game_state 또는 scenario 없음"}

    current_chapter = state.get("game_info", {}).get("current_chapter", 1)
    chapters = scenario.get("chapters", [])
    for ch in chapters:
        if ch.get("id") == current_chapter:
            return {
                "chapter": current_chapter,
                "name": ch.get("name", ""),
                "description": ch.get("description", ""),
                "objectives": ch.get("objectives", []),
                "turn": state.get("turn_count", 0),
            }
    return {"chapter": current_chapter, "name": "알 수 없음"}


def main():
    if len(sys.argv) < 2:
        print("사용법: python -m core.scenario_agent <check|quests|chapter_info>")
        return

    cmd = sys.argv[1]

    if cmd == "check":
        warnings = check_and_warn()
        if not warnings:
            print("✓ 시나리오 정합성 검증 통과")
        else:
            print(f"⚠ 감지 {len(warnings)}건:")
            for w in warnings:
                print(f"  {w}")

    elif cmd == "quests":
        result = quest_summary()
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif cmd == "chapter_info":
        result = chapter_info()
        print(json.dumps(result, ensure_ascii=False, indent=2))

    else:
        print(f"알 수 없는 명령: {cmd}")


if __name__ == "__main__":
    main()
