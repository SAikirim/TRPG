"""
Worldbuilding Agent — location/faction/NPC consistency verification.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class WorldbuildingRequest(BaseModel):
    """Request to Worldbuilding agent."""
    narration_text: str = Field(
        default="",
        description="Draft narration text to verify against world settings"
    )
    mentioned_locations: list[str] = Field(default_factory=list)
    mentioned_npcs: list[str] = Field(default_factory=list)
    mentioned_factions: list[str] = Field(default_factory=list)
    new_location: Optional[dict[str, Any]] = Field(
        default=None,
        description="{id, name, type, description, world_pos, connections}"
    )
    new_faction: Optional[dict[str, Any]] = Field(
        default=None,
        description="{id, name, description}"
    )
    validate_only: bool = False


class ConsistencyIssue(BaseModel):
    """Single consistency problem found."""
    severity: str = "warning"              # warning / error
    category: str = ""                     # location / faction / npc / currency / lore
    message: str = ""
    suggestion: Optional[str] = None


class WorldbuildingResponse(BaseModel):
    """Response from Worldbuilding agent."""
    is_consistent: bool = True
    issues: list[ConsistencyIssue] = Field(default_factory=list)
    registered_locations: list[str] = Field(
        default_factory=list,
        description="Location IDs that were newly registered"
    )
    registered_factions: list[str] = Field(default_factory=list)
    location_details: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Verified location info for mentioned locations"
    )
