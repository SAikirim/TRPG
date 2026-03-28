"""
GM 턴 추적기 — 실제 동작만 기록하고, 턴 종료 시 누락 경고.
가짜 상태 출력 절대 금지: 기록된 것만 표시.

사용법:
  python gm_turn.py start                     턴 처리 시작 (tracker 초기화)
  python gm_turn.py log <tag> <msg>           실제 수행한 작업 기록
  python gm_turn.py phase <phase_id> [msg]    단계 시작 기록
  python gm_turn.py agent <name> <detail>     에이전트 호출 기록
  python gm_turn.py end                       턴 종료 검증 (누락 경고)
  python gm_turn.py status                    현재 턴 진행 상황

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

단계(phase) 태그:
  1a — GM 방향 설정
  1b — 에이전트 호출
  2  — 나레이션 작성
  3  — 시스템 반영

순서 규칙:
  gm-update → narration (나레이션 기록 후 출력, write-before-display)
  gm-update가 없으면 narration 기록 시 경고 출력

출력 규칙 (show_system_log):
  ① 단계 헤더 → 항상 표시
  ② 에이전트 이름 → 항상 표시
  ③ 세부 내용 → show_system_log: true일 때만 표시
  ④ 내부 로그 → 무조건 기록 (.turn_tracker.json)
"""

import json
import os
import sys
sys.stdout.reconfigure(encoding='utf-8')
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRACKER_PATH = os.path.join(BASE_DIR, ".turn_tracker.json")
SESSION_PATH = os.path.join(BASE_DIR, "data", "current_session.json")

# 단계 헤더 이름
PHASE_NAMES = {
    "1a": "GM 방향 설정",
    "1b": "에이전트 호출",
    "2": "나레이션 작성",
    "3": "시스템 반영",
}


def _get_show_system_log():
    """current_session.json에서 show_system_log 설정을 읽는다."""
    try:
        with open(SESSION_PATH, "r", encoding="utf-8") as f:
            session = json.load(f)
        return session.get("show_system_log", False)
    except Exception:
        return False

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
        "phases": [],
        "agents": [],
        "completed": False,
    }
    _save_tracker(tracker)
    print("━━━ GM 턴 시작 ━━━")


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
    # narration 기록 시 gm-update가 먼저 되었는지 검증
    if tag == "narration":
        done_tags = {s["tag"] for s in tracker["steps"]}
        if "gm-update" not in done_tags:
            print("  ⚠️  경고: 나레이션 출력 전에 gm-update가 호출되지 않았습니다!")
            print("     → 나레이션이 game_state.json events에 기록되지 않습니다.")
            print("     → 세션 복원 시 이 턴의 내용이 사라집니다.")

    icon = icons.get(tag, "▸")
    print(f"  {icon} [{tag}] {message}")


def log_phase(phase_id, detail=""):
    """단계 시작을 기록한다. 헤더는 항상 표시, 세부 내용은 show_system_log에 따름."""
    tracker = _load_tracker()
    if not tracker:
        tracker = {
            "started_at": datetime.now().isoformat(),
            "steps": [],
            "phases": [],
            "agents": [],
            "completed": False,
        }

    phase_name = PHASE_NAMES.get(phase_id, phase_id)
    entry = {
        "phase": phase_id,
        "name": phase_name,
        "detail": detail,
        "time": datetime.now().isoformat(),
    }

    if "phases" not in tracker:
        tracker["phases"] = []
    tracker["phases"].append(entry)
    _save_tracker(tracker)

    # 단계 헤더는 항상 표시
    print(f"\n  [{phase_id}] {phase_name}")

    # 세부 내용은 show_system_log가 true일 때만
    if detail and _get_show_system_log():
        for line in detail.split("\n"):
            if line.strip():
                print(f"    → {line.strip()}")


def log_agent(agent_name, detail=""):
    """에이전트 호출을 기록한다. 이름은 항상 표시, 세부 내용은 show_system_log에 따름."""
    tracker = _load_tracker()
    if not tracker:
        tracker = {
            "started_at": datetime.now().isoformat(),
            "steps": [],
            "phases": [],
            "agents": [],
            "completed": False,
        }

    entry = {
        "agent": agent_name,
        "detail": detail,
        "time": datetime.now().isoformat(),
    }

    if "agents" not in tracker:
        tracker["agents"] = []
    tracker["agents"].append(entry)
    _save_tracker(tracker)

    # 에이전트 이름은 항상 표시
    print(f"    → Agent [{agent_name}]")

    # 세부 내용은 show_system_log가 true일 때만
    if detail and _get_show_system_log():
        for line in detail.split("\n"):
            if line.strip():
                print(f"      - {line.strip()}")


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

    # 순서 검증: gm-update가 narration보다 먼저 기록되었는지
    gm_update_time = None
    narration_time = None
    for s in tracker["steps"]:
        if s["tag"] == "gm-update" and gm_update_time is None:
            gm_update_time = s["time"]
        if s["tag"] == "narration" and narration_time is None:
            narration_time = s["time"]

    if narration_time and not gm_update_time:
        warnings.append("  ⚠️  순서 위반: 나레이션이 출력되었으나 gm-update가 호출되지 않음 → events 미기록")
    elif narration_time and gm_update_time and narration_time < gm_update_time:
        warnings.append("  ⚠️  순서 위반: 나레이션이 gm-update보다 먼저 출력됨 → write-before-display 위반")

    # 위치 변경 누락 체크: 나레이션에 이동 키워드가 있는데 location 갱신이 없으면 경고
    has_location_update = any(
        s["tag"] == "gm-update" and "location" in s.get("detail", "").lower()
        for s in tracker["steps"]
    )
    if not has_location_update:
        # 에이전트 결과나 나레이션에서 이동 키워드 탐지
        move_keywords = ["도착", "이동", "들어서", "진입", "떠나", "출발", "쉼터에", "마을에", "성문"]
        all_details = " ".join(
            a.get("detail", "") for a in tracker.get("agents", [])
        ) + " " + " ".join(
            p.get("message", "") for p in tracker.get("phases", [])
        )
        if any(kw in all_details for kw in move_keywords):
            warnings.append("  ⚠️  위치 변경 누락 가능: 나레이션에 이동 키워드 감지됨 → gm-update에 location 필드 추가 필요")

    # GM 행동 강화 검증: narration + 플레이어 행동 요약
    if "narration" in done_tags:
        has_player_action = any(
            s["tag"] == "narration" and ("플레이어 행동" in s.get("message", "")
                                         or "Player Actions" in s.get("message", ""))
            for s in tracker["steps"]
        )
        # 다른 로그에서도 플레이어 행동 기록 확인
        if not has_player_action:
            has_player_action = any(
                "플레이어 행동" in s.get("message", "") or "Player Actions" in s.get("message", "")
                for s in tracker["steps"]
            )
        if not has_player_action:
            warnings.append("  ⚠️ 플레이어 행동 요약 미출력")

    # GM 행동 강화 검증: dice 판정 시 나레이션에 🎲 인라인 표시
    if "dice" in done_tags:
        narration_msgs = [
            s.get("message", "") for s in tracker["steps"] if s["tag"] == "narration"
        ]
        has_dice_emoji = any("🎲" in msg for msg in narration_msgs)
        if not has_dice_emoji:
            warnings.append("  ⚠️ 나레이션에 🎲 인라인 판정 표시 누락")

    tracker["completed"] = True
    tracker["ended_at"] = datetime.now().isoformat()
    _save_tracker(tracker)

    if warnings:
        print("━━━ GM 턴 종료 — 경고 ━━━")
        for w in warnings:
            print(w)
        print("━━━━━━━━━━━━━━━━━━━━━")
    else:
        print("━━━ GM 턴 완료 ✓ ━━━")

    # 수행 요약
    phases = tracker.get("phases", [])
    agents = tracker.get("agents", [])
    steps = tracker.get("steps", [])
    total = len(phases) + len(agents) + len(steps)
    print(f"  수행된 작업: {total}건 (단계 {len(phases)}, 에이전트 {len(agents)}, 태그 {len(steps)})")

    # 단계별 요약 (내부 로그이므로 항상 전부 출력)
    for p in phases:
        detail_str = f" — {p['detail']}" if p.get("detail") else ""
        print(f"    [{p['phase']}] {p['name']}{detail_str}")
    for a in agents:
        detail_str = f" — {a['detail']}" if a.get("detail") else ""
        print(f"    → Agent [{a['agent']}]{detail_str}")
    for s in steps:
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
        print("사용법: python gm_turn.py <start|log|phase|agent|end|status>")
        print("  start                     턴 처리 시작")
        print("  log <tag> <msg>           작업 기록")
        print("  phase <1a|1b|2|3> [msg]   단계 시작 기록")
        print("  agent <name> [detail]     에이전트 호출 기록")
        print("  end                       턴 종료 검증")
        print("  status                    진행 상황")
        print("  should_push [N]           N턴마다 push 필요 여부 (기본 3)")
        return

    cmd = sys.argv[1]

    if cmd == "start":
        start_turn()
    elif cmd == "log" and len(sys.argv) >= 4:
        log_step(sys.argv[2], " ".join(sys.argv[3:]))
    elif cmd == "phase" and len(sys.argv) >= 3:
        detail = " ".join(sys.argv[3:]) if len(sys.argv) >= 4 else ""
        log_phase(sys.argv[2], detail)
    elif cmd == "agent" and len(sys.argv) >= 3:
        detail = " ".join(sys.argv[3:]) if len(sys.argv) >= 4 else ""
        log_agent(sys.argv[2], detail)
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
