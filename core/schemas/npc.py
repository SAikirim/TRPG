"""
NPC Agent — dialogue, actions, proactive behavior.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class NPCAction(BaseModel):
    """Single NPC action/dialogue output."""
    npc_id: int
    npc_name: str
    dialogue: Optional[str] = None         # What the NPC says
    tone: str = "neutral"                  # serious / playful / angry / scared / etc.
    action: Optional[str] = None           # Physical action description
    emotion: Optional[str] = None          # Internal emotional state
    target: Optional[str] = None           # Who the NPC is addressing/acting toward
    memory_update: Optional[str] = None    # New key_event to add to NPC memory


class NPCRequest(BaseModel):
    """Request to NPC agent — can handle multiple NPCs in one call."""
    npc_ids: list[int] = Field(
        default_factory=list,
        description="NPC IDs to generate actions for"
    )
    party_actions: str = Field(
        default="",
        description="What the player party just did (trigger for NPC reactions)"
    )
    situation: str = Field(
        default="",
        description="Current scene description for context"
    )
    specific_questions: list[str] = Field(
        default_factory=list,
        description="GM's specific questions to the NPC agent"
    )
    # Full entity data loaded by runner from entities/{scenario}/npcs/
    npc_entities: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Full NPC entity JSON data (loaded by runner)"
    )


class NPCResponse(BaseModel):
    """Response from NPC agent."""
    actions: list[NPCAction] = Field(default_factory=list)
    npc_updates: list[dict[str, Any]] = Field(
        default_factory=list,
        description="[{id, field, value}] — state changes (hp, status, location, etc.)"
    )
    new_memories: list[dict[str, Any]] = Field(
        default_factory=list,
        description="[{npc_id, key_event}] — events to add to NPC memory"
    )
    relationship_changes: list[dict[str, Any]] = Field(
        default_factory=list,
        description="[{npc_id, target, old_relation, new_relation}]"
    )
