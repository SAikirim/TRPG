"""
Claude Runner — uses Claude Code's built-in Agent tool as execution backend.
This is the default runner when no external APIs are configured.

Usage:
  In Claude Code CLI, the main GM session spawns sub-agents via the Agent tool.
  This runner serializes the AgentRequest into a prompt, and the response
  is parsed back into an AgentResponse.

  Since Claude Code Agent tool is invoked by the main Claude session (not by Python),
  this runner provides:
  1. build_prompt() — generates the prompt to pass to Agent tool
  2. parse_response() — parses Agent tool output back to AgentResponse
  3. execute() — placeholder for programmatic invocation (future use)
"""

from __future__ import annotations

import json
from typing import Any

from core.schemas.base import (
    AgentConfig,
    AgentRequest,
    AgentResponse,
    AgentType,
    RunnerType,
)
from core.runners.base import AbstractRunner, AGENT_PROMPTS


class ClaudeRunner(AbstractRunner):
    """
    Runner that generates prompts for Claude Code Agent tool.

    Two usage modes:
    1. Prompt mode (default): build_prompt() returns a string for the Agent tool.
       The main GM session calls Agent tool with this prompt.
    2. Direct mode (future): execute() calls Claude API directly via SDK.
    """

    runner_type = RunnerType.CLAUDE

    def build_prompt(self, request: AgentRequest) -> str:
        """Build prompt for Claude Code Agent tool invocation."""
        agent_system = AGENT_PROMPTS.get(
            request.agent_type,
            f"You are the [{request.agent_type.value}] agent."
        )

        # Context section
        ctx = request.context
        context_lines = [
            f"Turn: {ctx.turn_number} | Chapter: {ctx.current_chapter}",
            f"Location: {ctx.current_location} | Time: {ctx.time_of_day}",
            f"Scenario: {ctx.scenario_id} | Ruleset: {ctx.ruleset}",
        ]
        if ctx.gm_direction:
            context_lines.append(f"GM Direction: {ctx.gm_direction}")

        # Player/NPC summaries (compact)
        if ctx.player_summary:
            context_lines.append(f"Players: {json.dumps(ctx.player_summary, ensure_ascii=False)}")
        if ctx.npc_summary:
            context_lines.append(f"NPCs: {json.dumps(ctx.npc_summary, ensure_ascii=False)}")

        # Recent events
        if ctx.recent_events:
            context_lines.append(f"Recent events: {json.dumps(ctx.recent_events, ensure_ascii=False)}")

        # Required files
        file_section = ""
        if request.required_files:
            file_section = (
                "\n\nRequired files to read before responding:\n"
                + "\n".join(f"- {f}" for f in request.required_files)
            )

        # Payload
        payload_json = json.dumps(request.payload, ensure_ascii=False, indent=2)

        prompt = f"""{agent_system}

--- CONTEXT ---
{chr(10).join(context_lines)}
{file_section}

--- REQUEST ---
{payload_json}

--- INSTRUCTIONS ---
1. Read all required files first.
2. Process the request according to your role.
3. Return ONLY valid JSON matching your response schema.
4. Include warnings for any consistency issues found.
"""
        return prompt

    def parse_response(self, raw_output: str, agent_type: AgentType) -> AgentResponse:
        """Parse Agent tool output (text) back into AgentResponse."""
        # Try to extract JSON from the output
        try:
            # Look for JSON block in markdown code fence
            if "```json" in raw_output:
                json_str = raw_output.split("```json")[1].split("```")[0].strip()
            elif "```" in raw_output:
                json_str = raw_output.split("```")[1].split("```")[0].strip()
            else:
                json_str = raw_output.strip()

            payload = json.loads(json_str)

            return AgentResponse(
                agent_type=agent_type,
                success=True,
                payload=payload,
                warnings=payload.pop("warnings", []),
                errors=payload.pop("errors", []),
            )
        except (json.JSONDecodeError, IndexError, KeyError) as e:
            return AgentResponse(
                agent_type=agent_type,
                success=False,
                payload={"raw_output": raw_output},
                errors=[f"Failed to parse agent output: {str(e)}"],
            )

    def execute(self, request: AgentRequest) -> AgentResponse:
        """
        Claude runner operates in prompt mode.
        Returns success=True with the built prompt in payload.
        The main Claude session uses this prompt to call Agent tool manually.
        """
        prompt = self.build_prompt(request)
        return AgentResponse(
            agent_type=request.agent_type,
            success=True,
            payload={
                "mode": "prompt",
                "prompt": prompt,
                "instruction": "Pass this prompt to Claude Code Agent tool for execution.",
            },
            runner_used=RunnerType.CLAUDE,
        )
