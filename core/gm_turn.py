"""
GM 턴 추적기 — 실제 동작만 기록하고, 턴 종료 시 누락 경고.
가짜 상태 출력 절대 금지: 기록된 것만 표시.

사용법:
  python gm_turn.py start              턴 처리 시작 (tracker 초기화)
  python gm_turn.py log <tag> <msg>    실제 수행한 작업 기록
  python gm_turn.py end                턴 종료 검증 (누락 경고)
  python gm_turn.py status             현재 턴 진행 상황

태그 목록:
  dice      — 주사위 판정 (game_mechanics.py 연동 시 자동)
  gm-update — gm-update API 호출
  state     — game_state.json 저장
  entity    — entities/ 파일 갱신
  save      — git commit + push
  npc       — NPC 대사/행동 생성
  narration — 나레이션 출력 완료
  worldbuilding — 세계관 검증 완료 (새 지역/세력/지리 반영 확인)
  rules — 룰 검증 완료 (판정/비용/사거리/상태이상 확인)
  scenario — 시나리오 검증 완료 (챕터 목표/퀘스트/이벤트 확인)
"""

import json
import os
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRACKER_PATH = os.path.join(BASE_DIR, ".turn_tracker.json")

# 턴에서 수행해야 할 필수 단계
REQUIRED_STEPS = {
    "gm-update": "gm-update API 호출 (웹 UI 반영)",
    "state": "game_state.json 저장",
    "narration": "나레이션 출력",
    "agent:worldbuilding": "세계관 에이전트 자동 검증",
    "agent:rules": "룰 에이전트 자동 검증",
    "agent:scenario": "시나리오 에이전트 자동 검증",
    "agent:npc": "NPC 에이전트 자동 검증",
    "agent:worldmap": "세계 지도 에이전트 자동 검증",
}

# 조건부 필수 (판정이 있었으면 dice 필요 등)
CONDITIONAL_STEPS = {
    "dice": "주사위 판정이 필요한 상황인데 판정 기록 없음",
}


def _load_tracker():
    if os.path.exists(TRACKER_PATH):
        with open(TRACKER_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def _save_tracker(data):
    with open(TRACKER_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def start_turn():
    """턴 처리 시작 — tracker 초기화"""
    tracker = {
        "started_at": datetime.now().isoformat(),
        "steps": [],
        "completed": False,
    }
    _save_tracker(tracker)
    print("━━━ Phase 1 시작 ━━━")


def log_step(tag, message):
    """실제 수행한 작업을 기록"""
    tracker = _load_tracker()
    if not tracker:
        # tracker 없이 호출됐으면 자동 시작
        tracker = {
            "started_at": datetime.now().isoformat(),
            "steps": [],
            "completed": False,
        }

    entry = {
        "tag": tag,
        "message": message,
        "time": datetime.now().isoformat(),
    }
    tracker["steps"].append(entry)
    _save_tracker(tracker)

    # 태그별 아이콘
    icons = {
        "dice": "🎲",
        "gm-update": "🖼️",
        "state": "💾",
        "entity": "📁",
        "save": "📌",
        "npc": "💬",
        "narration": "📖",
        "worldbuilding": "🌍",
        "rules": "⚖️",
        "scenario": "📜",
        "worldmap": "🗺️",
        # 자동 에이전트 검증 (app.py gm-update에서 자동 실행)
        "agent:worldbuilding": "🤖🌍",
        "agent:rules": "🤖⚖️",
        "agent:scenario": "🤖📜",
        "agent:npc": "🤖💬",
        "agent:worldmap": "🤖🗺️",
    }
    icon = icons.get(tag, "▸")
    print(f"  {icon} [{tag}] {message}")


def end_turn():
    """턴 종료 — 누락 검증"""
    tracker = _load_tracker()
    if not tracker:
        print("⚠️  활성 턴 없음 (start를 먼저 호출하세요)")
        return

    done_tags = {s["tag"] for s in tracker["steps"]}

    # 누락 체크
    warnings = []
    for tag, desc in REQUIRED_STEPS.items():
        if tag not in done_tags:
            warnings.append(f"  ⚠️  누락: {desc}")

    tracker["completed"] = True
    tracker["ended_at"] = datetime.now().isoformat()
    _save_tracker(tracker)

    if warnings:
        print("━━━ Phase 1 종료 — 경고 ━━━")
        for w in warnings:
            print(w)
        print("━━━━━━━━━━━━━━━━━━━━━")
    else:
        print("━━━ Phase 1 완료 ✓ ━━━")

    # 수행 요약
    print(f"  수행된 작업: {len(tracker['steps'])}건")
    for s in tracker["steps"]:
        icons = {"dice": "🎲", "gm-update": "🖼️", "state": "💾",
                 "entity": "📁", "save": "📌", "npc": "💬", "narration": "📖",
                 "worldbuilding": "🌍", "rules": "⚖️", "scenario": "📜"}
        icon = icons.get(s["tag"], "▸")
        print(f"    {icon} {s['message']}")


def show_status():
    """현재 턴 진행 상황"""
    tracker = _load_tracker()
    if not tracker:
        print("활성 턴 없음")
        return

    status = "완료" if tracker.get("completed") else "진행 중"
    print(f"턴 상태: {status} (시작: {tracker['started_at'][:19]})")
    print(f"수행 작업: {len(tracker['steps'])}건")

    done_tags = {s["tag"] for s in tracker["steps"]}
    for tag, desc in REQUIRED_STEPS.items():
        mark = "✓" if tag in done_tags else "✗"
        print(f"  [{mark}] {desc}")


def should_push(push_interval=3):
    """현재 턴에서 git push가 필요한지 판단.
    push_interval 턴마다 True 반환."""
    try:
        game_state_path = os.path.join(BASE_DIR, "data", "game_state.json")
        with open(game_state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
        turn = state.get("turn_count", 0)
        if turn == 0:
            return False
        return turn % push_interval == 0
    except Exception:
        return False


def main():
    if len(sys.argv) < 2:
        print("사용법: python gm_turn.py <start|log|end|status>")
        print("  start              턴 처리 시작")
        print("  log <tag> <msg>    작업 기록")
        print("  end                턴 종료 검증")
        print("  status             진행 상황")
        print("  should_push [N]    N턴마다 push 필요 여부 (기본 3)")
        return

    cmd = sys.argv[1]

    if cmd == "start":
        start_turn()
    elif cmd == "log" and len(sys.argv) >= 4:
        log_step(sys.argv[2], " ".join(sys.argv[3:]))
    elif cmd == "end":
        end_turn()
    elif cmd == "status":
        show_status()
    elif cmd == "should_push":
        interval = int(sys.argv[2]) if len(sys.argv) >= 3 else 3
        if should_push(interval):
            print("PUSH")
        else:
            print("SKIP")
    else:
        print(f"알 수 없는 명령: {cmd}")


if __name__ == "__main__":
    main()
