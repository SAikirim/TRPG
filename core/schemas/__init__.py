"""
Hybrid Multi-Agent Architecture — Pydantic Schemas
Unified request/response interface for all sub-agents.
Runner-agnostic: same schemas work with Claude Code Agent, Cloud API, or Local models.
"""

from core.schemas.base import (
    AgentType,
    RunnerType,
    AgentConfig,
    AgentRequest,
    AgentResponse,
    TurnContext,
)
from core.schemas.rule import RuleRequest, RuleResponse, DiceRoll
from core.schemas.npc import NPCRequest, NPCResponse, NPCAction
from core.schemas.player import PlayerRequest, PlayerResponse
from core.schemas.scenario import ScenarioRequest, ScenarioResponse
from core.schemas.worldbuilding import WorldbuildingRequest, WorldbuildingResponse
from core.schemas.worldmap import WorldMapRequest, WorldMapResponse
from core.schemas.system import SystemRequest, SystemResponse, GMUpdatePayload, DialogueLine
from core.schemas.orchestrator import TurnPlan, AgentDispatch, AgentCall, TurnSynthesis

__all__ = [
    # Base
    "AgentType", "RunnerType", "AgentConfig",
    "AgentRequest", "AgentResponse", "TurnContext",
    # Agent-specific
    "RuleRequest", "RuleResponse", "DiceRoll",
    "NPCRequest", "NPCResponse", "NPCAction",
    "PlayerRequest", "PlayerResponse",
    "ScenarioRequest", "ScenarioResponse",
    "WorldbuildingRequest", "WorldbuildingResponse",
    "WorldMapRequest", "WorldMapResponse",
    "SystemRequest", "SystemResponse", "GMUpdatePayload", "DialogueLine",
    # Orchestrator
    "TurnPlan", "AgentDispatch", "AgentCall", "TurnSynthesis",
]
