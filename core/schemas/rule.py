"""
Rule Arbiter Agent — dice rolls, skill checks, combat resolution.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class CheckType(str, Enum):
    SKILL_CHECK = "skill_check"
    ATTACK = "attack"
    DEFENSE = "defense"
    SAVE = "save"
    CONTEST = "contest"        # opposed check
    CUSTOM = "custom"


class DiceRoll(BaseModel):
    """Single dice roll result — maps to gm-update dice_rolls[] item."""
    type: CheckType = CheckType.SKILL_CHECK
    roller: str                            # Character name
    stat: str = ""                         # STR / DEX / INT / CON
    roll: int = 0                          # Raw d20 result
    modifier: int = 0                      # Stat modifier + bonuses
    total: int = 0                         # roll + modifier
    dc: int = 0                            # Difficulty class
    result: str = "pending"                # success / failure / critical / fumble
    damage: Optional[int] = None           # Damage dealt (if attack)
    damage_dice: Optional[str] = None      # e.g. "1d6+3"
    detail: str = ""                       # Human-readable explanation
    weapon: Optional[str] = None
    skill: Optional[str] = None
    mp_cost: int = 0
    element: Optional[str] = None
    on_hit_triggered: Optional[str] = None # poison / stun / bleed / lifesteal


class CombatAction(BaseModel):
    """Combat action request for a single character."""
    character_id: int
    character_name: str
    action: str                            # attack / skill / defend / flee / item
    target_id: Optional[int] = None
    target_name: Optional[str] = None
    skill_name: Optional[str] = None
    item_name: Optional[str] = None


class RuleRequest(BaseModel):
    """Request to Rule Arbiter agent."""
    checks: list[dict[str, Any]] = Field(
        default_factory=list,
        description="[{roller, stat, dc, type, context}] — skill checks to resolve"
    )
    combat_actions: list[CombatAction] = Field(
        default_factory=list,
        description="Combat actions to resolve in turn order"
    )
    status_effect_ticks: bool = Field(
        default=False,
        description="Process status effect durations (tick down / expire)"
    )
    validate_only: bool = Field(
        default=False,
        description="Only validate current state, don't roll dice"
    )


class RuleResponse(BaseModel):
    """Response from Rule Arbiter agent."""
    dice_rolls: list[DiceRoll] = Field(default_factory=list)
    state_changes: list[dict[str, Any]] = Field(
        default_factory=list,
        description="[{target_id, field, old_value, new_value}] — HP/MP/status changes"
    )
    turn_order: list[dict[str, Any]] = Field(
        default_factory=list,
        description="[{id, name, initiative}] — combat turn order if combat"
    )
    combat_log: list[str] = Field(
        default_factory=list,
        description="Human-readable combat sequence log"
    )
    expired_effects: list[dict[str, Any]] = Field(
        default_factory=list,
        description="[{character_id, effect_name}] — expired status effects"
    )
    validation_warnings: list[str] = Field(default_factory=list)
