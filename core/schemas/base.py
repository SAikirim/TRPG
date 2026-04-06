"""
Base schemas — shared by all agents and runners.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ─── Enums ───

class AgentType(str, Enum):
    RULE_ARBITER = "rule_arbiter"
    NPC = "npc"
    PLAYER = "player"
    SCENARIO = "scenario"
    WORLDBUILDING = "worldbuilding"
    WORLDMAP = "worldmap"
    SYSTEM = "system"


class RunnerType(str, Enum):
    CLAUDE = "claude"      # Claude Code Agent tool (built-in sub-agent)
    CLOUD = "cloud"        # External API (Gemini Flash, Groq/Llama, OpenAI, etc.)
    LOCAL = "local"        # Local model (Ollama, llama.cpp, etc.)


# ─── Agent Config ───

class AgentConfig(BaseModel):
    """Per-agent runner configuration."""
    agent_type: AgentType
    runner: RunnerType = RunnerType.CLAUDE
    model: Optional[str] = None           # e.g. "sonnet", "haiku", "gemini-1.5-flash"
    provider: Optional[str] = None        # e.g. "groq", "openai", "google", "ollama"
    endpoint: Optional[str] = None        # Custom API endpoint URL
    temperature: float = 0.7
    max_tokens: int = 4096
    system_prompt_path: Optional[str] = None  # Path to agent-specific system prompt
    fallback: list[RunnerType] = Field(
        default_factory=lambda: [RunnerType.CLAUDE],
        description="Fallback runner chain. Tried in order if primary runner fails."
    )


# ─── Turn Context (shared across all agent calls in a turn) ───

class TurnContext(BaseModel):
    """Snapshot of current game state passed to every agent call."""
    turn_number: int
    current_location: str
    current_chapter: int = 1
    time_of_day: str = "day"              # day / night / dawn / dusk
    scenario_id: str
    ruleset: str = "fantasy_basic"

    # Lightweight summaries (not full JSON — token efficiency)
    player_summary: list[dict[str, Any]] = Field(
        default_factory=list,
        description="[{id, name, class, hp, max_hp, mp, max_mp, position, status_effects}]"
    )
    npc_summary: list[dict[str, Any]] = Field(
        default_factory=list,
        description="[{id, name, type, status, location, hp, max_hp}]"
    )
    recent_events: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Last 5 events from game_state.events"
    )
    gm_direction: str = Field(
        default="",
        description="GM's phase-1a direction for this turn"
    )


# ─── Base Request / Response ───

class AgentRequest(BaseModel):
    """Common wrapper for all agent requests."""
    agent_type: AgentType
    context: TurnContext
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Agent-specific request data (cast to specific Request type by runner)"
    )
    required_files: list[str] = Field(
        default_factory=list,
        description="File paths the agent must read before processing"
    )
    timestamp: datetime = Field(default_factory=datetime.now)


class AgentResponse(BaseModel):
    """Common wrapper for all agent responses."""
    agent_type: AgentType
    success: bool = True
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Agent-specific response data"
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Non-fatal warnings from validation"
    )
    errors: list[str] = Field(
        default_factory=list,
        description="Fatal errors that block progression"
    )
    runner_used: RunnerType = RunnerType.CLAUDE
    duration_ms: Optional[int] = None
    timestamp: datetime = Field(default_factory=datetime.now)
