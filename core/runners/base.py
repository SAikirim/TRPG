"""
Abstract base runner — interface that all runners must implement.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any

from core.schemas.base import (
    AgentConfig,
    AgentRequest,
    AgentResponse,
    AgentType,
    RunnerType,
)


# 공통 언어 지시 (narration/dialogue/combat_log = 한국어, JSON key/시스템 필드 = 영어)
_LANG = (
    "\n\n[LANGUAGE RULE] All user-facing text MUST be in Korean (한국어):\n"
    "- narration: 한국어로 서술\n"
    "- dialogues[].line: 한국어 대사\n"
    "- combat_log: 한국어 전투 묘사\n"
    "- JSON keys, field names, stat names (STR/DEX/INT/CON), type values: keep English\n"
)

AGENT_PROMPTS: dict[AgentType, str] = {
    AgentType.RULE_ARBITER: (
        "You are the [Rule Arbiter] agent for a fantasy TRPG. Handle dice rolls, skill checks, combat.\n"
        "You MUST return JSON with EXACTLY these keys:\n"
        '{"narration": "판정/전투 결과를 한국어로 서술",'
        ' "dice_rolls": [{"type":"skill_check","roller":"name","stat":"DEX","roll":14,"modifier":3,"total":17,"dc":13,"result":"success"}],'
        ' "state_changes": [{"target_id":1,"field":"hp","old_value":21,"new_value":15}],'
        ' "combat_log": ["전투 과정을 단계별로 한국어 서술"],'
        ' "warnings": []}' + _LANG
    ),
    AgentType.NPC: (
        "You are the [NPC] agent for a fantasy TRPG. Generate dialogue and actions for NPCs.\n"
        "NPCs act proactively based on personality, memory, and relationships.\n\n"
        "[RELATIONSHIP SYSTEM]\n"
        "Each NPC has structured relationships with affinity (0-100) and trust (0-100) values.\n"
        "- 0-19: hatred/complete distrust | 20-39: dislike/wary | 40-59: neutral\n"
        "- 60-79: favorable/friendly | 80-100: deep bond/absolute trust\n"
        "You MUST read the NPC's relationships and let affinity/trust influence dialogue tone and actions.\n"
        "When an interaction changes a relationship, include relationship_changes in your response.\n\n"
        "You MUST return JSON with EXACTLY these keys:\n"
        '{"narration": "NPC의 행동과 장면을 한국어로 서술",'
        ' "dialogues": [{"speaker":"npc_name","line":"한국어 대사","tone":"serious"}],'
        ' "npc_updates": [{"id":300,"field":"value"}],'
        ' "new_memories": [{"npc_id":300,"key_event":"what happened"}],'
        ' "relationship_changes": [{"npc_id":300,"target":"saiki","affinity_delta":5,"trust_delta":3,"reason":"친절한 대화"}],'
        ' "warnings": []}' + _LANG
    ),
    AgentType.PLAYER: (
        "You are the [Player] agent for a fantasy TRPG. Generate actions for AI-controlled player characters.\n"
        "Never generate actions for user-controlled characters (controlled_by: user).\n"
        "You MUST return JSON with EXACTLY these keys:\n"
        '{"narration": "AI 플레이어 행동을 한국어로 서술",'
        ' "actions": [{"player_id":2,"player_name":"name","action":"한국어 행동","dialogue":"한국어 대사"}],'
        ' "player_updates": [{"id":2,"field":"value"}],'
        ' "warnings": []}' + _LANG
    ),
    AgentType.SCENARIO: (
        "You are the [Scenario] agent for a fantasy TRPG. Track chapter progression and quests.\n"
        "You MUST return JSON with EXACTLY these keys:\n"
        '{"narration": "시나리오 전개를 한국어로 서술",'
        ' "chapter_transition": null,'
        ' "quest_updates": [],'
        ' "story_flags": [],'
        ' "gm_hints": ["GM을 위한 제안 (한국어)"],'
        ' "warnings": []}' + _LANG
    ),
    AgentType.WORLDBUILDING: (
        "You are the [Worldbuilding] agent for a fantasy TRPG. Verify consistency with world settings.\n\n"
        "[LOCATION TRANSITION]\n"
        "When the party moves/departs/travels, you MUST set location_changed to the new location ID.\n"
        "- If destination exists in worldbuilding: use its ID (e.g. 'karendel', 'crossroads_rest')\n"
        "- If party is traveling between locations: create a waypoint ID (e.g. 'road_to_karendel_1')\n"
        "- If party stays at current location: set location_changed to null\n"
        "Keywords that trigger movement: 출발, 이동, 떠나다, travel, depart, move, head to, go to\n\n"
        "You MUST return JSON with EXACTLY these keys:\n"
        '{"narration": "세계관에 맞는 장면/분위기를 한국어로 서술",'
        ' "is_consistent": true,'
        ' "issues": [],'
        ' "location_changed": null,'
        ' "warnings": []}' + _LANG
    ),
    AgentType.WORLDMAP: (
        "You are the [World Map] agent for a fantasy TRPG. Verify geography and coordinates.\n"
        "You MUST return JSON with EXACTLY these keys:\n"
        '{"coordinate_issues": [],'
        ' "terrain_warnings": [],'
        ' "warnings": []}'
    ),
    AgentType.SYSTEM: (
        "You are the [System Reflection] agent for a fantasy TRPG. Assemble scene information.\n"
        "You MUST return JSON with EXACTLY these keys:\n"
        '{"illustration": {"type":"background","prompt":"landscape scene description for image generation (English)"},'
        ' "scene_update": null,'
        ' "events_recorded": [{"turn":0,"type":"narration","text":"이벤트 설명 (한국어)"}],'
        ' "warnings": []}'
    ),
}


class AbstractRunner(ABC):
    """
    Base class for all agent runners.
    Subclasses implement execute() for their specific backend.
    """

    runner_type: RunnerType

    def __init__(self, config: AgentConfig):
        self.config = config

    @abstractmethod
    def execute(self, request: AgentRequest) -> AgentResponse:
        """
        Execute an agent request and return a response.
        Must be implemented by each runner backend.
        """
        ...

    def run(self, request: AgentRequest) -> AgentResponse:
        """
        Wrapper with timing and error handling.
        Calls self.execute() internally.
        """
        start = time.perf_counter_ns()
        try:
            response = self.execute(request)
            response.runner_used = self.runner_type
            response.duration_ms = (time.perf_counter_ns() - start) // 1_000_000
            return response
        except Exception as e:
            elapsed = (time.perf_counter_ns() - start) // 1_000_000
            return AgentResponse(
                agent_type=request.agent_type,
                success=False,
                errors=[f"{self.runner_type.value} runner error: {str(e)}"],
                runner_used=self.runner_type,
                duration_ms=elapsed,
            )

    def _read_file_content(self, path: str, max_lines: int = 200) -> str:
        """Read a file and return its content (truncated). Handles dirs by listing JSON files."""
        import os as _os

        # Resolve relative paths from TRPG project root
        base_dir = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
        full_path = path if _os.path.isabs(path) else _os.path.join(base_dir, path)

        if _os.path.isdir(full_path):
            # Directory: read all JSON files (entity dirs, agents/, etc.)
            parts = []
            for fname in sorted(_os.listdir(full_path)):
                if not fname.endswith(".json"):
                    continue
                fpath = _os.path.join(full_path, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        data = f.read()
                    # Truncate large files
                    if len(data) > 3000:
                        data = data[:3000] + "\n...(truncated)"
                    parts.append(f"=== {fname} ===\n{data}")
                except Exception:
                    continue
            content = "\n".join(parts)
        elif _os.path.isfile(full_path):
            try:
                with open(full_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                if len(lines) > max_lines:
                    content = "".join(lines[:max_lines]) + "\n...(truncated)"
                else:
                    content = "".join(lines)
            except Exception:
                content = f"(failed to read {path})"
        else:
            content = ""

        return content

    def _build_file_context(self, request: AgentRequest) -> str:
        """Read required_files and build a file context section for the prompt."""
        if not request.required_files:
            return ""

        parts = []
        total_chars = 0
        max_total = 6000  # Token budget for file context (~1500 tokens, safe for 6K TPM)

        for fpath in request.required_files:
            if total_chars >= max_total:
                parts.append(f"\n[{fpath}: skipped — token budget reached]")
                break
            content = self._read_file_content(fpath)
            if content:
                remaining = max_total - total_chars
                if len(content) > remaining:
                    content = content[:remaining] + "\n...(truncated)"
                parts.append(f"\n--- FILE: {fpath} ---\n{content}")
                total_chars += len(content)

        return "\n".join(parts) if parts else ""

    def build_prompt(self, request: AgentRequest) -> str:
        """
        Build the text prompt sent to the model.
        Uses AGENT_PROMPTS for role-specific instructions with JSON schema.
        Injects required_files content into the prompt for cloud/local runners.
        """
        import json as _json

        agent_system = AGENT_PROMPTS.get(
            request.agent_type,
            f"You are the [{request.agent_type.value}] agent for a TRPG system."
        )

        ctx = request.context
        context_lines = [
            f"Turn: {ctx.turn_number} | Chapter: {ctx.current_chapter}",
            f"Location: {ctx.current_location} | Time: {ctx.time_of_day}",
            f"Scenario: {ctx.scenario_id} | Ruleset: {ctx.ruleset}",
        ]
        if ctx.gm_direction:
            context_lines.append(f"GM Direction: {ctx.gm_direction}")
        if ctx.player_summary:
            context_lines.append(f"Players: {_json.dumps(ctx.player_summary, ensure_ascii=False)}")
        if ctx.npc_summary:
            context_lines.append(f"NPCs: {_json.dumps(ctx.npc_summary, ensure_ascii=False)}")
        if ctx.recent_events:
            context_lines.append(f"Recent events: {_json.dumps(ctx.recent_events[-3:], ensure_ascii=False)}")

        # Read required files and inject content
        file_context = self._build_file_context(request)

        payload_json = _json.dumps(request.payload, ensure_ascii=False, indent=2)

        return f"""{agent_system}

--- CONTEXT ---
{chr(10).join(context_lines)}

--- REQUEST ---
{payload_json}
{file_context}

--- INSTRUCTIONS ---
Return ONLY valid JSON matching the schema above. Include the "narration" key with descriptive text."""
