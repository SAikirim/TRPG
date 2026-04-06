"""
System Reflection Agent — gm-update payload assembly, state save, git.
Maps directly to the existing /api/gm-update POST body.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


# ─── GMUpdate Payload (mirrors existing gm-update API) ───

class DialogueLine(BaseModel):
    speaker: str
    line: str
    tone: str = "neutral"


class IllustrationRequest(BaseModel):
    type: str = "background"               # background / portrait / effect / ui
    prompt: Optional[str] = None
    path: Optional[str] = None             # Use existing image instead of generating
    position: Optional[str] = None         # For portrait: far-left/left/center/right/far-right
    size_class: Optional[str] = None       # d1/d2/d3/d4
    layer_name: Optional[str] = None


class GMUpdatePayload(BaseModel):
    """
    Pydantic model for /api/gm-update POST body.
    Direct 1:1 mapping with existing Flask endpoint parameters.
    """
    description: str = ""
    narrative: str = ""

    # Player/NPC state changes
    player_updates: list[dict[str, Any]] = Field(default_factory=list)
    npc_updates: list[dict[str, Any]] = Field(default_factory=list)
    new_npcs: list[dict[str, Any]] = Field(default_factory=list)

    # Scene
    location: Optional[str] = None
    illustration: Optional[IllustrationRequest] = None
    scene_update: Optional[dict[str, Any]] = None
    clear_scene: bool = False
    remove_layer: Optional[str] = None

    # Dialogue & dice
    dialogues: list[DialogueLine] = Field(default_factory=list)
    dice_rolls: list[dict[str, Any]] = Field(default_factory=list)

    # Meta
    user_input: str = ""


# ─── System Agent Request / Response ───

class SystemRequest(BaseModel):
    """Request to System Reflection agent — assembles final gm-update from turn results."""
    narration: str = ""
    description: str = ""
    user_input: str = ""

    # Collected from other agents this turn
    dice_rolls: list[dict[str, Any]] = Field(default_factory=list)
    npc_actions: list[dict[str, Any]] = Field(default_factory=list)
    player_actions: list[dict[str, Any]] = Field(default_factory=list)
    state_changes: list[dict[str, Any]] = Field(default_factory=list)
    quest_updates: list[dict[str, Any]] = Field(default_factory=list)

    # Scene control
    location_changed: Optional[str] = None
    time_changed: Optional[str] = None
    chapter_changed: Optional[int] = None

    # Options
    should_save: bool = False
    should_git_push: bool = False


class SystemResponse(BaseModel):
    """Response from System Reflection agent."""
    gm_update_payload: GMUpdatePayload
    events_recorded: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Events added to game_state.events[]"
    )
    files_modified: list[str] = Field(
        default_factory=list,
        description="File paths that were updated"
    )
    save_result: Optional[str] = None      # "saved to slot_1" / None
    git_result: Optional[str] = None       # "pushed" / "committed" / None
