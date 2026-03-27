"""
Turn Orchestrator — main pipeline bridging game state with agent dispatch.

Flow: context → plan → dispatch → execute → synthesize → gm-update

Usage:
  from core.orchestrator import TurnOrchestrator
  python -m core.orchestrator turn "user action text"
  python -m core.orchestrator opening
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Optional

sys.stdout.reconfigure(encoding="utf-8")

# .env 파일에서 API key 자동 로드
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

import requests

from core.schemas import (
    AgentType,
    RunnerType,
    AgentConfig,
    AgentRequest,
    AgentResponse,
    TurnContext,
    RuleRequest,
    NPCRequest,
    PlayerRequest,
    ScenarioRequest,
    WorldbuildingRequest,
    WorldMapRequest,
    SystemRequest,
    GMUpdatePayload,
    DialogueLine,
    TurnPlan,
    AgentDispatch,
    AgentCall,
    TurnSynthesis,
)
from core.runners import AgentRegistry

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

logger = logging.getLogger(__name__)

# ─── 파일 경로 상수 ───
GAME_STATE_PATH = os.path.join(BASE_DIR, "data", "game_state.json")
SESSION_PATH = os.path.join(BASE_DIR, "data", "current_session.json")
WORLDBUILDING_PATH = os.path.join(BASE_DIR, "data", "worldbuilding.json")
RULES_PATH = os.path.join(BASE_DIR, "data", "rules.json")
SCENARIO_PATH = os.path.join(BASE_DIR, "data", "scenario.json")

GM_UPDATE_URL = "http://localhost:5000/api/gm-update"

# ─── 무드 키워드 매핑 ───
MOOD_KEYWORDS: dict[str, list[str]] = {
    "tense": ["attack", "fight", "combat", "kill", "defend", "flee", "공격", "전투", "싸우"],
    "calm": ["talk", "ask", "speak", "greet", "chat", "대화", "말", "인사"],
    "curious": ["look", "search", "examine", "inspect", "investigate", "조사", "살펴", "탐색"],
    "dramatic": ["sacrifice", "confess", "betray", "reveal", "희생", "고백", "배신"],
}

COMBAT_KEYWORDS = {"attack", "fight", "combat", "kill", "defend", "공격", "전투", "싸우", "때리"}


def _load_json(path: str) -> dict[str, Any]:
    """JSON 파일 로드 (UTF-8, FileNotFoundError 안전 처리)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning("File not found: %s", path)
        return {}
    except json.JSONDecodeError as e:
        logger.error("JSON decode error in %s: %s", path, e)
        return {}


class TurnOrchestrator:
    """
    Main GM orchestrator — coordinates the full turn pipeline.

    context → plan → dispatch → execute → synthesize → gm-update
    """

    def __init__(self, auto_detect: bool = True):
        self.registry = AgentRegistry(auto_detect=auto_detect)
        # Force refresh after dotenv is loaded (fixes import-order race)
        if auto_detect:
            self.registry.refresh_availability()
        # Pending events buffer — 턴 완료 전 대화/행동 임시 저장
        self.pending_events: list[dict[str, Any]] = []
        self.pending_dialogues: list[dict[str, Any]] = []

    # ─── Pending Events (턴 중간 대화/행동 기록) ───

    def record_event(self, text: str, speaker: str = "GM", event_type: str = "narration") -> None:
        """턴 중간 이벤트를 pending 버퍼에 기록. save 시 game_state에 flush."""
        game_state = _load_json(GAME_STATE_PATH)
        turn = game_state.get("turn_count", 0)
        self.pending_events.append({
            "turn": turn,
            "type": event_type,
            "speaker": speaker,
            "text": text,
            "timestamp": time.strftime("%H:%M:%S"),
        })

    def record_dialogue(self, speaker: str, line: str, tone: str = "neutral", target: str = "") -> None:
        """턴 중간 대사를 pending 버퍼에 기록."""
        self.pending_dialogues.append({
            "speaker": speaker,
            "line": line,
            "tone": tone,
            **({"target": target} if target else {}),
        })

    def record_user_action(self, action: str) -> None:
        """유저 행동 선언을 pending에 기록."""
        self.record_event(action, speaker="user", event_type="action")

    def flush_pending(self) -> int:
        """Pending events/dialogues를 game_state.json에 하나의 이벤트로 기록. 반환: 기록된 이벤트 수."""
        if not self.pending_events and not self.pending_dialogues:
            return 0

        game_state = _load_json(GAME_STATE_PATH)
        turn = game_state.get("turn_count", 0)

        # 모든 pending을 하나의 이벤트로 통합
        narratives = []
        user_input = ""
        for evt in self.pending_events:
            if evt.get("speaker") == "user":
                user_input = evt.get("text", "")
            else:
                narratives.append(evt.get("text", ""))

        event = {
            "turn": turn,
            "message": f"[GM] 턴 중간 기록 (pending flush)",
            "narrative": "\n\n".join(narratives),
            "user_input": user_input,
            "dialogues": list(self.pending_dialogues),
            "timestamp": time.strftime("%H:%M:%S"),
        }
        game_state.setdefault("events", []).append(event)

        # 저장
        with open(GAME_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(game_state, f, ensure_ascii=False, indent=2)

        count = len(self.pending_events) + len(self.pending_dialogues)

        # 버퍼 클리어
        self.pending_events.clear()
        self.pending_dialogues.clear()

        return count

    def save(self, description: str = "") -> dict:
        """
        수동 저장 — pending 이벤트 flush → 세이브 슬롯 저장 → git commit.
        턴 완료 전이라도 모든 대화/행동이 보존됨.
        gm-update는 flush 후 game_state 재로드로 웹 동기화.
        """
        result = {"flushed": 0, "gm_update": False, "saved": False, "git": False}

        # 1. Flush pending events → game_state.json에 기록
        flushed = self.flush_pending()
        result["flushed"] = flushed

        # 2. 웹 UI 동기화 — game_state를 재로드하여 최신 상태 반영
        game_state = _load_json(GAME_STATE_PATH)
        session = _load_json(SESSION_PATH)
        try:
            resp = requests.post(
                "http://localhost:5000/api/load",
                json={"reload": True},
                timeout=5,
            )
            result["gm_update"] = resp.status_code == 200
        except Exception:
            # /api/load 없으면 gm-update로 최소 동기화 (narrative 없이, 덮어쓰기 방지)
            try:
                resp = requests.get("http://localhost:5000/api/game-state", timeout=3)
                result["gm_update"] = resp.status_code == 200
            except Exception:
                pass

        # 3. 세이브 슬롯 저장
        try:
            from core.save_manager import SaveManager
            sm = SaveManager()
            scenario_id = session.get("active_scenario", game_state.get("game_info", {}).get("scenario_id", ""))
            slot = session.get("active_save_slot", 1)
            save_desc = description or f"수동 저장 (턴 {game_state.get('turn_count', 0)})"
            save_result = sm.save_game(scenario_id, slot=slot, description=save_desc, overwrite=True)
            result["saved"] = save_result is not None
        except Exception as e:
            logger.error("Save failed: %s", e)

        # 4. git commit + push (수동 저장은 반드시 push)
        try:
            subprocess.run(
                ["git", "add", "-A"],
                cwd=BASE_DIR, capture_output=True, timeout=10,
            )
            subprocess.run(
                ["git", "commit", "-m", f"save: {description or 'manual save'}"],
                cwd=BASE_DIR, capture_output=True, timeout=10,
            )
            result["git"] = True
            # push (백그라운드)
            subprocess.Popen(
                ["git", "push"],
                cwd=BASE_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            result["pushed"] = True
        except Exception as e:
            logger.error("Git commit/push failed: %s", e)

        return result

    # ─── Phase 0: Build Context ───

    def build_context(self) -> TurnContext:
        """Read game state files and build TurnContext."""
        game_state = _load_json(GAME_STATE_PATH)
        session = _load_json(SESSION_PATH)
        worldbuilding = _load_json(WORLDBUILDING_PATH)

        # 플레이어 요약 (compact)
        player_summary = []
        for p in game_state.get("players", []):
            player_summary.append({
                "id": p.get("id", ""),
                "name": p.get("name", ""),
                "class": p.get("class", ""),
                "hp": p.get("hp", 0),
                "max_hp": p.get("max_hp", 0),
                "mp": p.get("mp", 0),
                "max_mp": p.get("max_mp", 0),
                "position": p.get("position", ""),
                "status_effects": p.get("status_effects", []),
            })

        # NPC 요약 (compact)
        npc_summary = []
        for n in game_state.get("npcs", []):
            npc_summary.append({
                "id": n.get("id", ""),
                "name": n.get("name", ""),
                "type": n.get("type", ""),
                "status": n.get("status", "active"),
                "location": n.get("location", ""),
                "hp": n.get("hp", 0),
                "max_hp": n.get("max_hp", 0),
            })

        # 최근 이벤트 (마지막 5개)
        events = game_state.get("events", [])
        recent_events = events[-5:] if len(events) > 5 else events

        # 시간대
        time_of_day = session.get("time_of_day", "day")

        # 시나리오 ID: session > game_state > fallback
        game_info = game_state.get("game_info", {})
        scenario_id = (
            session.get("scenario_id")
            or game_info.get("scenario_id")
            or "unknown"
        )

        return TurnContext(
            turn_number=session.get("turn", game_info.get("turn_count", 0)),
            current_location=game_state.get("current_location", ""),
            current_chapter=session.get("chapter", 1),
            time_of_day=time_of_day,
            scenario_id=scenario_id,
            ruleset=game_info.get("ruleset", "fantasy_basic"),
            player_summary=player_summary,
            npc_summary=npc_summary,
            recent_events=recent_events,
        )

    # ─── Phase 1a: Plan Turn ───

    def plan_turn(self, user_action: str, context: TurnContext) -> TurnPlan:
        """Create TurnPlan from user action. GM direction is determined here."""
        action_lower = user_action.lower()

        # 무드 결정
        mood = "neutral"
        for m, keywords in MOOD_KEYWORDS.items():
            if any(kw in action_lower for kw in keywords):
                mood = m
                break

        # 전투 여부
        is_combat = any(kw in action_lower for kw in COMBAT_KEYWORDS)

        # 필수 에이전트: worldbuilding, scenario, system
        agents_needed = [
            AgentType.WORLDBUILDING,
            AgentType.SCENARIO,
            AgentType.SYSTEM,
        ]

        # 전투/판정 → rule_arbiter
        if is_combat or any(kw in action_lower for kw in ["check", "roll", "판정", "굴려"]):
            agents_needed.append(AgentType.RULE_ARBITER)

        # NPC 존재 → npc agent
        if context.npc_summary:
            agents_needed.append(AgentType.NPC)

        # AI 플레이어 존재 → player agent (controlled_by != "user")
        has_ai_players = any(
            p.get("controlled_by") != "user"
            for p in _load_json(GAME_STATE_PATH).get("players", [])
            if "controlled_by" in p
        )
        if has_ai_players:
            agents_needed.append(AgentType.PLAYER)

        # GM 방향 설정
        gm_direction = f"User action: {user_action}"
        if is_combat:
            gm_direction += " | Combat encounter — resolve attacks, apply damage."
        if mood == "tense":
            gm_direction += " | Tense atmosphere — emphasize danger."

        return TurnPlan(
            turn_number=context.turn_number,
            user_action=user_action,
            gm_direction=gm_direction,
            mood=mood,
            agents_needed=agents_needed,
            is_combat=is_combat,
        )

    # ─── Phase 1b: Build Dispatch ───

    def build_dispatch(self, plan: TurnPlan, context: TurnContext) -> AgentDispatch:
        """Create AgentDispatch with appropriate agent calls based on plan."""
        # 에이전트별 required_files 매핑
        scenario_id = context.scenario_id
        required_files_map: dict[AgentType, list[str]] = {
            AgentType.RULE_ARBITER: ["data/rules.json", "data/skills.json"],
            AgentType.NPC: [f"entities/{scenario_id}/npcs/"],
            AgentType.PLAYER: ["agents/", f"entities/{scenario_id}/players/"],
            AgentType.SCENARIO: ["data/scenario.json", "data/quests.json"],
            AgentType.WORLDBUILDING: ["data/worldbuilding.json"],
            AgentType.WORLDMAP: ["data/worldbuilding.json"],
            AgentType.SYSTEM: ["data/game_state.json", "data/current_session.json"],
        }

        # 에이전트별 우선순위 + 의존성
        # worldbuilding/scenario → 독립 (priority 1)
        # rule_arbiter → 독립 (priority 1)
        # npc/player → worldbuilding 완료 후 (priority 2)
        # system → 모든 에이전트 완료 후 (priority 3)
        priority_map: dict[AgentType, int] = {
            AgentType.WORLDBUILDING: 1,
            AgentType.SCENARIO: 1,
            AgentType.WORLDMAP: 1,
            AgentType.RULE_ARBITER: 1,
            AgentType.NPC: 2,
            AgentType.PLAYER: 2,
            AgentType.SYSTEM: 3,
        }

        depends_map: dict[AgentType, list[AgentType]] = {
            AgentType.NPC: [AgentType.WORLDBUILDING],
            AgentType.PLAYER: [AgentType.WORLDBUILDING],
            AgentType.SYSTEM: [],  # system은 synthesize 이후에 호출하므로 의존성 없음
        }

        # context에 gm_direction 반영
        ctx = context.model_copy(update={"gm_direction": plan.gm_direction})

        calls: list[AgentCall] = []
        for agent_type in plan.agents_needed:
            call = AgentCall(
                agent_type=agent_type,
                priority=priority_map.get(agent_type, 2),
                depends_on=depends_map.get(agent_type, []),
                payload={
                    "user_action": plan.user_action,
                    "mood": plan.mood,
                    "is_combat": plan.is_combat,
                    "gm_direction": plan.gm_direction,
                },
                required_files=required_files_map.get(agent_type, []),
            )
            calls.append(call)

        return AgentDispatch(
            turn_number=plan.turn_number,
            context=ctx,
            calls=calls,
        )

    # ─── Execute Dispatch (runner별 병렬) ───

    def execute_dispatch(self, dispatch: AgentDispatch) -> dict[str, AgentResponse]:
        """Runner별 병렬 실행. 같은 runner는 순차, 다른 runner는 동시.
        Dependency groups도 존중 (group 1 완료 후 group 2)."""
        results: dict[str, AgentResponse] = {}

        for group in dispatch.parallel_groups():
            # Runner별로 분류
            runner_groups: dict[str, list[AgentCall]] = {}
            for call in group:
                cfg = self.registry.config.get(call.agent_type)
                runner_key = cfg.runner.value if cfg else "claude"
                runner_groups.setdefault(runner_key, []).append(call)

            def _run_runner_batch(calls: list[AgentCall]) -> list[tuple[str, AgentResponse]]:
                """같은 runner의 call들을 순차 실행."""
                batch_results = []
                for call in calls:
                    request = self._build_request(call, dispatch.context)
                    response = self._execute_single(call, request)
                    batch_results.append((call.agent_type.value, response))
                return batch_results

            if len(runner_groups) == 1:
                # 단일 runner → 순차
                for calls in runner_groups.values():
                    for key, resp in _run_runner_batch(calls):
                        results[key] = resp
            else:
                # 다른 runner끼리 병렬
                with ThreadPoolExecutor(max_workers=len(runner_groups)) as executor:
                    futures = {
                        executor.submit(_run_runner_batch, calls): runner_key
                        for runner_key, calls in runner_groups.items()
                    }
                    for future in as_completed(futures):
                        try:
                            for key, resp in future.result():
                                results[key] = resp
                        except Exception as e:
                            runner_key = futures[future]
                            logger.error("Runner batch %s failed: %s", runner_key, e)

        return results

    def _build_request(self, call: AgentCall, context: TurnContext) -> AgentRequest:
        """AgentCall → AgentRequest 변환."""
        return AgentRequest(
            agent_type=call.agent_type,
            context=context,
            payload=call.payload,
            required_files=call.required_files,
        )

    def _execute_single(self, call: AgentCall, request: AgentRequest) -> AgentResponse:
        """
        단일 에이전트 실행.
        - cloud/local runner → dispatch() → AgentResponse 직접 반환
        - claude runner → dispatch() → AgentResponse with mode="prompt" in payload
        """
        start_ms = time.time()
        try:
            # registry.dispatch 가 runner 해석 + fallback 처리
            response = self.registry.dispatch(request)
            elapsed = int((time.time() - start_ms) * 1000)
            response.duration_ms = elapsed
            return response
        except Exception as e:
            elapsed = int((time.time() - start_ms) * 1000)
            logger.error("Agent %s execution error: %s", call.agent_type.value, e)
            return AgentResponse(
                agent_type=call.agent_type,
                success=False,
                errors=[f"Execution error: {e}"],
                duration_ms=elapsed,
            )

    # ─── Phase 2: Synthesize ───

    def synthesize(
        self,
        plan: TurnPlan,
        results: dict[str, AgentResponse],
        context: TurnContext,
    ) -> TurnSynthesis:
        """Merge agent results into TurnSynthesis."""
        synthesis = TurnSynthesis(
            turn_number=plan.turn_number,
            agent_results=results,
        )
        synthesis.merge_warnings()

        # 나레이션 조합: NPC 행동 + 플레이어 행동 + GM 방향
        narration_parts: list[str] = []

        # NPC 에이전트 결과
        npc_resp = results.get(AgentType.NPC.value)
        if npc_resp and npc_resp.success:
            npc_narration = npc_resp.payload.get("narration", "")
            if npc_narration:
                narration_parts.append(npc_narration)
            # 대화 추출
            for dialogue in npc_resp.payload.get("dialogues", []):
                synthesis.dialogues.append(dialogue)

        # 플레이어 에이전트 결과
        player_resp = results.get(AgentType.PLAYER.value)
        if player_resp and player_resp.success:
            player_narration = player_resp.payload.get("narration", "")
            if player_narration:
                narration_parts.append(player_narration)

        # 시나리오 에이전트 결과 (이벤트/전개)
        scenario_resp = results.get(AgentType.SCENARIO.value)
        if scenario_resp and scenario_resp.success:
            scenario_narration = scenario_resp.payload.get("narration", "")
            if scenario_narration:
                narration_parts.append(scenario_narration)

        # 룰 에이전트 결과 (판정 결과)
        rule_resp = results.get(AgentType.RULE_ARBITER.value)
        if rule_resp and rule_resp.success:
            rule_narration = rule_resp.payload.get("narration", "")
            if rule_narration:
                narration_parts.append(rule_narration)

        synthesis.narration = "\n\n".join(narration_parts)
        synthesis.description = f"Turn {plan.turn_number}: {plan.user_action[:80]}"

        return synthesis

    # ─── Phase 3: Build gm-update Payload ───

    def build_gm_update(
        self,
        synthesis: TurnSynthesis,
        plan: TurnPlan,
        context: TurnContext,
    ) -> GMUpdatePayload:
        """Build final gm-update payload from synthesis results."""
        results = synthesis.agent_results

        # 기본 payload
        payload = GMUpdatePayload(
            description=synthesis.description,
            narrative=synthesis.narration,
            user_input=plan.user_action,
        )

        # 대화
        for d in synthesis.dialogues:
            payload.dialogues.append(DialogueLine(
                speaker=d.get("speaker", ""),
                line=d.get("line", ""),
                tone=d.get("tone", "neutral"),
            ))

        # 판정 결과 (dice_rolls)
        rule_resp = results.get(AgentType.RULE_ARBITER.value)
        if rule_resp and rule_resp.success:
            payload.dice_rolls = rule_resp.payload.get("dice_rolls", [])

        # NPC 업데이트
        npc_resp = results.get(AgentType.NPC.value)
        if npc_resp and npc_resp.success:
            payload.npc_updates = npc_resp.payload.get("npc_updates", [])
            payload.new_npcs = npc_resp.payload.get("new_npcs", [])

        # 플레이어 업데이트
        player_resp = results.get(AgentType.PLAYER.value)
        if player_resp and player_resp.success:
            payload.player_updates = player_resp.payload.get("player_updates", [])

        # 위치 변경
        worldbuilding_resp = results.get(AgentType.WORLDBUILDING.value)
        if worldbuilding_resp and worldbuilding_resp.success:
            new_location = worldbuilding_resp.payload.get("location_changed")
            if new_location:
                payload.location = new_location

        # 시스템 에이전트가 illustration 등 추가 정보 제공
        system_resp = results.get(AgentType.SYSTEM.value)
        if system_resp and system_resp.success:
            illustration_data = system_resp.payload.get("illustration")
            if illustration_data:
                from core.schemas.system import IllustrationRequest
                payload.illustration = IllustrationRequest(**illustration_data)
            scene_update = system_resp.payload.get("scene_update")
            if scene_update:
                payload.scene_update = scene_update

        return payload

    # ─── gm-update API Call ───

    def send_gm_update(self, payload: GMUpdatePayload) -> bool:
        """POST to /api/gm-update. Returns success."""
        try:
            resp = requests.post(
                GM_UPDATE_URL,
                json=payload.model_dump(exclude_none=True),
                timeout=10,
            )
            if resp.status_code == 200:
                logger.info("gm-update sent successfully")
                return True
            else:
                logger.error("gm-update failed: %d %s", resp.status_code, resp.text[:200])
                return False
        except requests.ConnectionError:
            logger.error("gm-update connection failed — Flask server not running?")
            return False
        except Exception as e:
            logger.error("gm-update error: %s", e)
            return False

    # ─── Session Startup (CLAUDE.md 세션 절차) ───

    def ensure_session(self) -> list[str]:
        """
        CLAUDE.md 세션 절차 1-5단계 자동 실행.
        1. CLAUDE.md 확인 (orchestrator가 대신 준수)
        2. session_validator 실행
        3. 데이터 파일 로드 확인
        4. guides/gm_rules.txt 확인
        5. Flask 서버 확인 → 미실행 시 자동 기동
        Returns list of warnings/actions taken.
        """
        log: list[str] = []

        # Step 2: session_validator
        validator_path = os.path.join(BASE_DIR, "session_validator.py")
        if os.path.isfile(validator_path):
            try:
                result = subprocess.run(
                    [sys.executable, validator_path],
                    capture_output=True, text=True, encoding="utf-8", timeout=30,
                )
                if result.returncode != 0:
                    log.append(f"session_validator warning: {result.stdout[-200:]}")
                else:
                    log.append("session_validator: OK")
            except Exception as e:
                log.append(f"session_validator error: {e}")

        # Step 3: data file existence
        for name, path in [
            ("game_state", GAME_STATE_PATH),
            ("current_session", SESSION_PATH),
            ("worldbuilding", WORLDBUILDING_PATH),
            ("rules", RULES_PATH),
            ("scenario", SCENARIO_PATH),
        ]:
            if not os.path.isfile(path):
                log.append(f"MISSING: {name} ({path})")

        # Step 4: guides check
        gm_rules_path = os.path.join(BASE_DIR, "guides", "gm_rules.txt")
        if not os.path.isfile(gm_rules_path):
            log.append("MISSING: guides/gm_rules.txt")

        # Step 5: Flask server → auto-start if not running
        flask_ok = False
        try:
            resp = requests.get("http://localhost:5000/api/game-state", timeout=3)
            flask_ok = resp.status_code == 200
        except Exception:
            pass

        if flask_ok:
            log.append("Flask server: running")
        else:
            log.append("Flask server: not running → starting...")
            self._start_flask_server()
            # Verify after startup
            import time as _time
            for _ in range(10):
                _time.sleep(1)
                try:
                    resp = requests.get("http://localhost:5000/api/game-state", timeout=2)
                    if resp.status_code == 200:
                        flask_ok = True
                        break
                except Exception:
                    continue
            if flask_ok:
                log.append("Flask server: started OK")
            else:
                log.append("Flask server: FAILED to start — web UI unavailable")

        # Step 6: 맵 재생성 (현재 위치 기준)
        map_ok = self._regenerate_map()
        log.append(f"Map: {'regenerated' if map_ok else 'failed (non-critical)'}")

        # Step 7: 장면 복원 (gm-update로 NPC 레이어 등)
        if flask_ok:
            try:
                requests.post(GM_UPDATE_URL, json={"description": "Session restore"}, timeout=5)
                log.append("Scene: restored")
            except Exception:
                log.append("Scene: restore failed")

        return log

    def _regenerate_map(self) -> bool:
        """로컬 맵 + 월드맵 재생성. SD venv Python 사용."""
        sd_python = os.path.join("C:\\", "git", "WebUI", "stable-diffusion-webui", "venv", "Scripts", "Python.exe")
        if not os.path.isfile(sd_python):
            sd_python = sys.executable
        try:
            # 로컬 맵
            subprocess.run(
                [sd_python, "-c", "from core.map_generator import MapGenerator; MapGenerator().save_map()"],
                cwd=BASE_DIR, capture_output=True, timeout=30,
            )
            # 월드맵
            subprocess.run(
                [sd_python, "-c", "from core.world_map import generate_world_map; generate_world_map()"],
                cwd=BASE_DIR, capture_output=True, timeout=30,
            )
            return True
        except Exception as e:
            logger.warning("Map regeneration failed: %s", e)
            return False

    def _start_flask_server(self) -> None:
        """Flask 서버를 백그라운드로 기동."""
        # SD venv Python 우선, 없으면 시스템 Python
        sd_python = os.path.join("C:\\", "git", "WebUI", "stable-diffusion-webui", "venv", "Scripts", "Python.exe")
        if not os.path.isfile(sd_python):
            sd_python = sys.executable

        app_path = os.path.join(BASE_DIR, "app.py")
        try:
            subprocess.Popen(
                [sd_python, app_path],
                cwd=BASE_DIR,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as e:
            logger.error("Failed to start Flask server: %s", e)

    # ─── Game Progression (턴 카운터, 시간, 위치, NPC 동기화) ───

    _last_location_change: Optional[str] = None

    # 시간 경과 순서 (3턴마다 한 단계 진행)
    TIME_CYCLE = ["dawn", "day", "day", "dusk", "night", "night"]

    def _advance_game_state(
        self, results: dict[str, AgentResponse], context: TurnContext
    ) -> None:
        """턴 종료 시 게임 상태 자동 업데이트."""
        game_state = _load_json(GAME_STATE_PATH)
        session = _load_json(SESSION_PATH)
        changed = False

        # 1. 턴 카운터 +1
        old_turn = game_state.get("turn_count", 0)
        game_state["turn_count"] = old_turn + 1
        session["turn"] = old_turn + 1
        changed = True

        # 2. 시간 경과 (6턴 = 1 사이클: dawn→day→day→dusk→night→night)
        cycle_idx = (old_turn + 1) % len(self.TIME_CYCLE)
        new_time = self.TIME_CYCLE[cycle_idx]
        old_time = session.get("time_of_day", "day")
        if new_time != old_time:
            session["time_of_day"] = new_time
            logger.info("Time: %s → %s", old_time, new_time)

        # 3. 위치 이동 (worldbuilding agent가 location_changed 제안한 경우)
        self._last_location_change = None
        wb_resp = results.get(AgentType.WORLDBUILDING.value)
        new_location = None
        if wb_resp and wb_resp.success:
            new_location = wb_resp.payload.get("location_changed")

        if new_location and new_location != game_state.get("current_location"):
            old_location = game_state.get("current_location", "")
            game_state["current_location"] = new_location
            session["current_location"] = new_location
            self._last_location_change = new_location
            logger.info("Location: %s → %s", old_location, new_location)

            # 3a. 중간 지점 자동 생성 (worldbuilding에 없으면)
            wb = _load_json(WORLDBUILDING_PATH)
            if new_location not in wb.get("locations", {}):
                self._create_waypoint(new_location, old_location, wb)

            # 3b. 동행 NPC 위치 동기화
            self._sync_npc_locations(game_state, new_location)

        # 저장
        if changed:
            with open(GAME_STATE_PATH, "w", encoding="utf-8") as f:
                json.dump(game_state, f, ensure_ascii=False, indent=2)
            with open(SESSION_PATH, "w", encoding="utf-8") as f:
                json.dump(session, f, ensure_ascii=False, indent=2)

    def _create_waypoint(self, new_loc_id: str, from_loc_id: str, wb: dict) -> None:
        """이동 중 중간 지점을 worldbuilding에 자동 등록."""
        locations = wb.get("locations", {})
        from_loc = locations.get(from_loc_id, {})
        from_pos = from_loc.get("world_pos")

        # 목적지 찾기 (connections에서)
        dest_id = None
        for conn_id, conn in from_loc.get("connections", {}).items():
            # new_loc_id가 경로상 중간지점이름이면 목적지는 connection의 다음 위치
            dest_id = conn_id
            break

        if not from_pos:
            return

        # 목적지 위치
        to_loc = locations.get(dest_id, {}) if dest_id else {}
        to_pos = to_loc.get("world_pos")

        if to_pos:
            # 중간 지점 좌표 = from과 to 사이 30% 지점
            mid_x = int(from_pos[0] + (to_pos[0] - from_pos[0]) * 0.3)
            mid_y = int(from_pos[1] + (to_pos[1] - from_pos[1]) * 0.3)
        else:
            # 목적지 없으면 from에서 약간 이동
            mid_x = from_pos[0] + 3
            mid_y = from_pos[1] - 3

        # worldbuilding에 등록
        locations[new_loc_id] = {
            "name": new_loc_id.replace("_", " ").title(),
            "type": "road",
            "world_pos": [mid_x, mid_y],
            "description": f"Waypoint between {from_loc_id} and {dest_id or 'unknown'}",
            "connections": {
                from_loc_id: {"direction": "back", "distance_km": 5},
            },
            "map": from_loc.get("map", {}),  # 임시: 출발지 맵 재사용
        }
        if dest_id:
            locations[new_loc_id]["connections"][dest_id] = {"direction": "forward", "distance_km": 10}

        wb["locations"] = locations
        with open(WORLDBUILDING_PATH, "w", encoding="utf-8") as f:
            json.dump(wb, f, ensure_ascii=False, indent=2)

        logger.info("Waypoint created: %s at [%d,%d]", new_loc_id, mid_x, mid_y)

    def _sync_npc_locations(self, game_state: dict, new_location: str) -> None:
        """동행 NPC(friendly + 현재 위치에 있는)의 location을 새 위치로 동기화."""
        old_location = game_state.get("current_location", "")
        for npc in game_state.get("npcs", []):
            if npc.get("status") != "alive":
                continue
            npc_loc = npc.get("location", "")
            # 동행 조건: friendly이고 이전 위치에 있었던 NPC
            if npc.get("type") == "friendly" and (npc_loc == old_location or not npc_loc):
                npc["location"] = new_location
            # neutral이라도 같은 위치에 있으면 (행상인, 검사 등 합류한 NPC)
            elif npc_loc == old_location:
                npc["location"] = new_location

    # ─── Relationship Changes → Entity File Update ───

    def _apply_relationship_changes(
        self, results: dict[str, AgentResponse], context: TurnContext
    ) -> int:
        """NPC 에이전트의 relationship_changes를 entity 파일에 반영. 반환: 변경 수."""
        npc_resp = results.get(AgentType.NPC.value)
        if not npc_resp or not npc_resp.success:
            return 0

        changes = npc_resp.payload.get("relationship_changes", [])
        if not changes:
            return 0

        scenario_id = context.scenario_id
        npc_dir = os.path.join(BASE_DIR, "entities", scenario_id, "npcs")
        count = 0

        for change in changes:
            npc_id = change.get("npc_id")
            target = change.get("target", "")
            affinity_delta = change.get("affinity_delta", 0)
            trust_delta = change.get("trust_delta", 0)
            reason = change.get("reason", "")

            if not npc_id or not target:
                continue

            # Find entity file
            entity_path = os.path.join(npc_dir, f"npc_{npc_id}.json")
            if not os.path.isfile(entity_path):
                continue

            try:
                with open(entity_path, "r", encoding="utf-8") as f:
                    entity = json.load(f)

                rels = entity.get("relationships", {})
                rel = rels.get(target, {})

                # Handle old text-only format gracefully
                if isinstance(rel, str):
                    rel = {"description": rel, "affinity": 50, "trust": 50, "history": []}

                # Apply deltas (clamp 0-100)
                old_aff = rel.get("affinity", 50)
                old_trust = rel.get("trust", 50)
                rel["affinity"] = max(0, min(100, old_aff + affinity_delta))
                rel["trust"] = max(0, min(100, old_trust + trust_delta))

                # Add history entry
                rel.setdefault("history", []).append({
                    "turn": context.turn_number,
                    "change": affinity_delta,
                    "reason": reason,
                })

                rels[target] = rel
                entity["relationships"] = rels

                with open(entity_path, "w", encoding="utf-8") as f:
                    json.dump(entity, f, ensure_ascii=False, indent=2)

                logger.info(
                    "Relationship: %s→%s affinity %d→%d, trust %d→%d (%s)",
                    entity.get("name", npc_id), target,
                    old_aff, rel["affinity"], old_trust, rel["trust"], reason,
                )
                count += 1

            except Exception as e:
                logger.error("Failed to update relationship for npc_%s: %s", npc_id, e)

        return count

    # ─── Auto Save (git commit + push) ───

    def _auto_save(self, turn: int, description: str = "") -> None:
        """매 턴 git commit, 3턴마다 push."""
        try:
            subprocess.run(
                ["git", "add", "-A"],
                cwd=BASE_DIR, capture_output=True, timeout=10,
            )
            subprocess.run(
                ["git", "commit", "-m", f"turn {turn}: {description}"],
                cwd=BASE_DIR, capture_output=True, timeout=10,
            )
            # 매 턴 push (백그라운드)
            subprocess.Popen(
                ["git", "push"],
                cwd=BASE_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            logger.error("Auto-save failed: %s", e)

    # ─── gm_turn.py Integration ───

    def _call_gm_turn(self, *args: str) -> None:
        """gm_turn.py를 subprocess로 호출."""
        cmd = [sys.executable, os.path.join(BASE_DIR, "core", "gm_turn.py")] + list(args)
        try:
            subprocess.run(cmd, check=False, capture_output=True, text=True, encoding="utf-8")
        except Exception as e:
            logger.warning("gm_turn.py call failed: %s", e)

    # ─── Action Collection (행동 수집) ───

    def _collect_player_actions(
        self, user_actions: dict[int, str], context: TurnContext
    ) -> dict[int, str]:
        """
        모든 플레이어의 행동을 수집.
        - user 캐릭터: user_actions에서 가져옴 (player_id → action text)
        - ai 캐릭터: Player Agent로 자동 생성
        Returns: {player_id: action_text} for all players.
        """
        game_state = _load_json(GAME_STATE_PATH)
        all_actions: dict[int, str] = {}

        # AI 플레이어 목록
        ai_player_ids = []
        for p in game_state.get("players", []):
            pid = p.get("id")
            if pid in user_actions:
                all_actions[pid] = user_actions[pid]
            elif p.get("controlled_by") == "ai":
                ai_player_ids.append(pid)

        # AI 플레이어 행동 생성 (Player Agent)
        if ai_player_ids:
            # 유저 행동을 상황 정보로 전달
            user_action_summary = "; ".join(
                f"{self._get_player_name(game_state, pid)}: {action}"
                for pid, action in user_actions.items()
            )

            req = AgentRequest(
                agent_type=AgentType.PLAYER,
                context=context.model_copy(update={
                    "gm_direction": f"User actions this turn: {user_action_summary}",
                }),
                payload={
                    "player_ids": ai_player_ids,
                    "user_actions": user_action_summary,
                    "situation": context.gm_direction,
                    "is_combat": False,
                },
                required_files=[
                    "agents/",
                    f"entities/{context.scenario_id}/players/",
                ],
            )
            resp = self.registry.dispatch(req)
            if resp.success:
                # 에이전트 응답에서 각 AI 플레이어 행동 추출
                for action_data in resp.payload.get("actions", []):
                    pid = action_data.get("player_id")
                    action_text = action_data.get("action", "")
                    dialogue = action_data.get("dialogue", "")
                    if pid and (action_text or dialogue):
                        all_actions[pid] = f"{action_text} {dialogue}".strip()

                # 행동이 생성 안 된 AI 플레이어 → 기본 행동
                for pid in ai_player_ids:
                    if pid not in all_actions:
                        all_actions[pid] = "주변을 경계하며 따라간다."

        return all_actions

    @staticmethod
    def _get_player_name(game_state: dict, player_id: int) -> str:
        for p in game_state.get("players", []):
            if p.get("id") == player_id:
                return p.get("name", f"player_{player_id}")
        return f"player_{player_id}"

    # ─── Full Turn Pipeline ───

    def run_turn(self, user_action: str, user_actions: Optional[dict[int, str]] = None) -> TurnSynthesis:
        """
        Full turn pipeline — 모든 플레이어 행동 수집 후 턴 처리.

        Args:
            user_action: 유저의 행동 텍스트 (단일 유저 모드)
            user_actions: {player_id: action} (멀티 유저 모드, 선택)
                         미지정 시 user_action을 controlled_by="user" 캐릭터에 할당
        """
        # Session startup (CLAUDE.md 절차 1-5)
        session_log = self.ensure_session()
        for entry in session_log:
            logger.info("Session: %s", entry)

        # gm_turn start
        self._call_gm_turn("start")

        # Phase 0: build context
        context = self.build_context()

        # ─── 행동 수집 단계 ───
        # user_actions가 없으면 user_action을 user 캐릭터에 할당
        if user_actions is None:
            game_state = _load_json(GAME_STATE_PATH)
            user_actions = {}
            for p in game_state.get("players", []):
                if p.get("controlled_by") == "user":
                    user_actions[p["id"]] = user_action

        # 모든 플레이어 행동 수집 (user + AI)
        all_actions = self._collect_player_actions(user_actions, context)
        all_actions_summary = "; ".join(
            f"{self._get_player_name(_load_json(GAME_STATE_PATH), pid)}: {act}"
            for pid, act in all_actions.items()
        )
        logger.info("Actions collected: %s", all_actions_summary)

        # Phase 1a: plan (전체 행동 기반)
        self._call_gm_turn("phase", "1a", "GM direction setting")
        plan = self.plan_turn(all_actions_summary, context)

        # Phase 1b: dispatch + execute (Player Agent 제외 — 이미 수집됨)
        self._call_gm_turn("phase", "1b", "Agent dispatch")
        # Player는 이미 수집했으므로 agents_needed에서 제거
        plan.agents_needed = [a for a in plan.agents_needed if a != AgentType.PLAYER]
        dispatch = self.build_dispatch(plan, context)
        results = self.execute_dispatch(dispatch)

        # 에이전트 호출 기록
        for agent_key in results:
            self._call_gm_turn("agent", agent_key, "completed")

        # Player 행동을 결과에 추가 (synthesize에서 사용)
        results[AgentType.PLAYER.value] = AgentResponse(
            agent_type=AgentType.PLAYER,
            success=True,
            payload={
                "narration": "",
                "actions": [
                    {"player_id": pid, "player_name": self._get_player_name(_load_json(GAME_STATE_PATH), pid), "action": act}
                    for pid, act in all_actions.items()
                ],
            },
        )

        # Phase 2: synthesize
        self._call_gm_turn("phase", "2", "Narration synthesis")
        synthesis = self.synthesize(plan, results, context)

        # Relationship changes → entity 파일 반영
        self._apply_relationship_changes(results, context)

        # Game progression: 턴 카운터 + 시간 + 위치 + NPC 동기화
        self._advance_game_state(results, context)

        # Phase 3: gm-update
        self._call_gm_turn("phase", "3", "System reflection")
        gm_payload = self.build_gm_update(synthesis, plan, context)
        success = self.send_gm_update(gm_payload)
        if success:
            self._call_gm_turn("log", "gm-update", "sent")
        else:
            logger.warning("gm-update failed — narration may not appear on web UI")

        self._call_gm_turn("log", "narration", "completed")

        # 위치 변경 시 맵 재생성
        new_loc = self._last_location_change
        if new_loc and new_loc != context.current_location:
            self._regenerate_map()
            logger.info("Map regenerated for new location: %s", new_loc)

        # git commit + push (매 턴)
        self._auto_save(context.turn_number + 1, f"turn {context.turn_number + 1}")

        # gm_turn end
        self._call_gm_turn("end")

        return synthesis

    # ─── Turn 0: Opening Narration ───

    def run_opening(self) -> TurnSynthesis:
        """Turn 0: opening narration after game_start.py initialization."""
        # Session startup (CLAUDE.md 절차 1-5)
        session_log = self.ensure_session()
        for entry in session_log:
            logger.info("Session: %s", entry)

        self._call_gm_turn("start")

        # scenario.json의 opening 정보 로드
        scenario = _load_json(SCENARIO_PATH)
        opening = scenario.get("opening", {})
        opening_narrative = opening.get("narrative", "")

        # context 빌드
        context = self.build_context()
        ctx = context.model_copy(update={"gm_direction": "Opening narration — introduce the world and characters."})

        # opening에 필요한 에이전트만 호출: worldbuilding, scenario, system
        self._call_gm_turn("phase", "1a", "Opening direction")
        self._call_gm_turn("phase", "1b", "Opening agents")

        opening_agents = [AgentType.WORLDBUILDING, AgentType.SCENARIO, AgentType.SYSTEM]
        calls: list[AgentCall] = []
        required_files_map: dict[AgentType, list[str]] = {
            AgentType.WORLDBUILDING: ["data/worldbuilding.json"],
            AgentType.SCENARIO: ["data/scenario.json", "data/quests.json"],
            AgentType.SYSTEM: ["data/game_state.json", "data/current_session.json"],
        }

        for agent_type in opening_agents:
            calls.append(AgentCall(
                agent_type=agent_type,
                priority=1 if agent_type != AgentType.SYSTEM else 2,
                payload={
                    "is_opening": True,
                    "opening_narrative": opening_narrative,
                    "gm_direction": "Opening narration",
                },
                required_files=required_files_map.get(agent_type, []),
            ))

        dispatch = AgentDispatch(
            turn_number=0,
            context=ctx,
            calls=calls,
        )

        results = self.execute_dispatch(dispatch)
        for agent_key in results:
            self._call_gm_turn("agent", agent_key, "completed")

        # synthesis 빌드
        self._call_gm_turn("phase", "2", "Opening narration")
        synthesis = TurnSynthesis(
            turn_number=0,
            agent_results=results,
            narration=opening_narrative,
            description="Turn 0: Opening",
        )
        synthesis.merge_warnings()

        # gm-update (배경 일러스트 포함)
        self._call_gm_turn("phase", "3", "Opening system reflection")
        gm_payload = GMUpdatePayload(
            description="Opening narration",
            narrative=opening_narrative,
        )

        # system agent가 illustration 정보를 제공한 경우
        system_resp = results.get(AgentType.SYSTEM.value)
        if system_resp and system_resp.success:
            illustration_data = system_resp.payload.get("illustration")
            if illustration_data:
                from core.schemas.system import IllustrationRequest
                gm_payload.illustration = IllustrationRequest(**illustration_data)

        success = self.send_gm_update(gm_payload)
        if success:
            self._call_gm_turn("log", "gm-update", "opening sent")
        self._call_gm_turn("log", "narration", "opening completed")
        self._call_gm_turn("end")

        return synthesis

    # ─── Status ───

    def status(self) -> dict:
        """Return current orchestrator status (registry config, availability, token usage)."""
        # Token usage from cloud runner sessions
        token_info = {}
        try:
            from core.runners.cloud import CloudRunner
            if hasattr(CloudRunner, '_session_mgr'):
                token_info = {
                    "per_agent": CloudRunner._session_mgr.status(),
                    "total": CloudRunner._session_mgr.total_usage(),
                }
        except Exception:
            pass

        return {
            "registry_config": self.registry.get_config_summary(),
            "fallback_log": self.registry.get_fallback_log(),
            "token_usage": token_info,
            "data_files": {
                "game_state": os.path.isfile(GAME_STATE_PATH),
                "current_session": os.path.isfile(SESSION_PATH),
                "worldbuilding": os.path.isfile(WORLDBUILDING_PATH),
                "rules": os.path.isfile(RULES_PATH),
                "scenario": os.path.isfile(SCENARIO_PATH),
            },
        }


# ─── CLI Entry Point ───

def main():
    """CLI: python -m core.orchestrator <command> [args]"""
    import argparse

    parser = argparse.ArgumentParser(description="TRPG Turn Orchestrator")
    subparsers = parser.add_subparsers(dest="command")

    # turn 커맨드
    turn_parser = subparsers.add_parser("turn", help="Execute a full turn")
    turn_parser.add_argument("action", type=str, help="User action text")

    # opening 커맨드
    subparsers.add_parser("opening", help="Execute opening narration (Turn 0)")

    # save 커맨드
    save_parser = subparsers.add_parser("save", help="Manual save (flush pending + save slot + git)")
    save_parser.add_argument("description", nargs="?", default="", help="Save description")

    # status 커맨드
    subparsers.add_parser("status", help="Show orchestrator status")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    orchestrator = TurnOrchestrator(auto_detect=True)

    if args.command == "turn":
        synthesis = orchestrator.run_turn(args.action)
        print(f"\n{'='*60}")
        print(f"Turn {synthesis.turn_number} complete")
        if synthesis.narration:
            print(f"\n{synthesis.narration}")
        if synthesis.all_warnings:
            print(f"\nWarnings: {synthesis.all_warnings}")
        if synthesis.all_errors:
            print(f"\nErrors: {synthesis.all_errors}")

    elif args.command == "opening":
        synthesis = orchestrator.run_opening()
        print(f"\n{'='*60}")
        print("Opening narration complete")
        if synthesis.narration:
            print(f"\n{synthesis.narration}")

    elif args.command == "save":
        result = orchestrator.save(args.description)
        print(f"Flushed: {result['flushed']} pending events")
        print(f"gm-update: {'OK' if result['gm_update'] else 'FAIL'}")
        print(f"Save slot: {'OK' if result['saved'] else 'FAIL'}")
        print(f"Git commit: {'OK' if result['git'] else 'FAIL'}")

    elif args.command == "status":
        status = orchestrator.status()
        print(json.dumps(status, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
