"""
Scenario Agent — chapter progression, quest tracking, ending branches.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class QuestUpdate(BaseModel):
    """Quest state change."""
    quest_id: str
    status: str                            # active / completed / failed / discovered
    objective_updates: list[dict[str, Any]] = Field(
        default_factory=list,
        description="[{objective_id, completed: bool}]"
    )
    reward: Optional[dict[str, Any]] = None


class ScenarioRequest(BaseModel):
    """Request to Scenario agent."""
    events_this_turn: list[str] = Field(
        default_factory=list,
        description="Key events that happened this turn"
    )
    npc_deaths: list[str] = Field(
        default_factory=list,
        description="NPCs that died this turn (may trigger story branches)"
    )
    location_entered: Optional[str] = None
    items_obtained: list[str] = Field(default_factory=list)
    check_chapter_transition: bool = True
    check_quest_completion: bool = True


class ScenarioResponse(BaseModel):
    """Response from Scenario agent."""
    chapter_transition: Optional[dict[str, Any]] = Field(
        default=None,
        description="{from_chapter, to_chapter, trigger_reason}"
    )
    quest_updates: list[QuestUpdate] = Field(default_factory=list)
    new_quests_discovered: list[dict[str, Any]] = Field(
        default_factory=list,
        description="[{quest_id, title, description, objectives}]"
    )
    story_flags: list[str] = Field(
        default_factory=list,
        description="Narrative flags set by this turn's events"
    )
    ending_triggered: Optional[dict[str, Any]] = Field(
        default=None,
        description="{ending_id, title, reason}"
    )
    gm_hints: list[str] = Field(
        default_factory=list,
        description="Suggestions for GM narration direction"
    )
