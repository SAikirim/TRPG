"""
Player Agent — AI-controlled player character decisions.
(User-controlled characters are excluded; only controlled_by: "ai")
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class PlayerAction(BaseModel):
    """Single AI player action output."""
    player_id: int
    player_name: str
    action: str                            # What the character does
    dialogue: Optional[str] = None         # What the character says
    target: Optional[str] = None           # Action target
    skill_used: Optional[str] = None       # Skill name if using a skill
    item_used: Optional[str] = None        # Item name if using an item
    reasoning: str = Field(
        default="",
        description="Brief reasoning for the action (for GM context, not displayed)"
    )


class PlayerRequest(BaseModel):
    """Request to Player agent."""
    player_ids: list[int] = Field(
        default_factory=list,
        description="AI player IDs to generate actions for"
    )
    situation: str = Field(
        default="",
        description="Current scene/situation description"
    )
    user_action: str = Field(
        default="",
        description="What the user character just did"
    )
    available_actions: list[str] = Field(
        default_factory=list,
        description="Actions available in current context"
    )
    is_combat: bool = False
    # Full data loaded by runner
    agent_data: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Agent personality data from agents/agent_*.json"
    )
    character_data: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Character entity data from entities/{scenario}/players/"
    )


class PlayerResponse(BaseModel):
    """Response from Player agent."""
    actions: list[PlayerAction] = Field(default_factory=list)
    party_dialogue: list[dict[str, Any]] = Field(
        default_factory=list,
        description="[{speaker, line, tone}] — inter-party conversation"
    )
