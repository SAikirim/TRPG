"""
GM Orchestrator schemas — turn planning, agent dispatch, result synthesis.
Used by the Main GM (Claude) to coordinate sub-agents.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from core.schemas.base import AgentType, TurnContext, AgentResponse


class AgentCall(BaseModel):
    """Single agent call specification in a dispatch plan."""
    agent_type: AgentType
    priority: int = 1                      # 1=highest, called first
    depends_on: list[AgentType] = Field(
        default_factory=list,
        description="Agent types that must complete before this call"
    )
    payload: dict[str, Any] = Field(default_factory=dict)
    required_files: list[str] = Field(default_factory=list)


class TurnPlan(BaseModel):
    """Phase 1a — GM direction setting."""
    turn_number: int
    user_action: str                       # What the user declared
    gm_direction: str                      # GM's narrative direction for this turn
    mood: str = "neutral"                  # tense / calm / comedic / dramatic / etc.
    expected_events: list[str] = Field(
        default_factory=list,
        description="Key events the GM expects to happen this turn"
    )
    agents_needed: list[AgentType] = Field(
        default_factory=list,
        description="Which agents to call this turn"
    )
    is_combat: bool = False
    notes: str = ""


class AgentDispatch(BaseModel):
    """Phase 1b — agent call plan with dependency ordering."""
    turn_number: int
    context: TurnContext
    calls: list[AgentCall] = Field(default_factory=list)

    def parallel_groups(self) -> list[list[AgentCall]]:
        """
        Group calls by priority + dependencies into parallelizable batches.
        Returns list of groups; calls within each group can run in parallel.
        """
        completed: set[AgentType] = set()
        remaining = list(self.calls)
        groups: list[list[AgentCall]] = []

        while remaining:
            # Find calls whose dependencies are all completed
            ready = [
                c for c in remaining
                if all(dep in completed for dep in c.depends_on)
            ]
            if not ready:
                # Deadlock — force remaining into one group
                groups.append(remaining)
                break

            # Sort ready calls by priority
            ready.sort(key=lambda c: c.priority)
            groups.append(ready)

            for c in ready:
                completed.add(c.agent_type)
                remaining.remove(c)

        return groups


class TurnSynthesis(BaseModel):
    """Phase 2 — synthesized result from all agent responses."""
    turn_number: int
    agent_results: dict[str, AgentResponse] = Field(
        default_factory=dict,
        description="AgentType.value → AgentResponse"
    )
    narration: str = ""                    # Final narration text
    description: str = ""                  # Short description for gm-update
    dialogues: list[dict[str, Any]] = Field(default_factory=list)
    all_warnings: list[str] = Field(default_factory=list)
    all_errors: list[str] = Field(default_factory=list)

    def has_errors(self) -> bool:
        return len(self.all_errors) > 0

    def merge_warnings(self) -> None:
        """Collect all warnings from agent results."""
        self.all_warnings = []
        self.all_errors = []
        for resp in self.agent_results.values():
            self.all_warnings.extend(resp.warnings)
            self.all_errors.extend(resp.errors)
