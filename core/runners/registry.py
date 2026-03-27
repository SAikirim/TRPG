"""
Agent Registry — maps AgentType → Runner based on configuration.
Central dispatch point for all agent calls.
Supports auto-detection of available backends and fallback chains.
"""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from typing import Optional

from core.schemas.base import (
    AgentConfig,
    AgentRequest,
    AgentResponse,
    AgentType,
    RunnerType,
    TurnContext,
)
from core.runners.base import AbstractRunner
from core.runners.claude import ClaudeRunner
from core.runners.cloud import CloudRunner
from core.runners.local import LocalRunner


# Config file path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_PATH = os.path.join(BASE_DIR, "data", "agent_config.json")

# Default config: all agents use Claude runner
DEFAULT_CONFIG: dict[str, dict] = {
    "rule_arbiter":  {"runner": "claude", "model": "sonnet"},
    "npc":           {"runner": "claude", "model": "haiku"},
    "player":        {"runner": "claude", "model": "haiku"},
    "scenario":      {"runner": "claude", "model": "sonnet"},
    "worldbuilding": {"runner": "claude", "model": "sonnet"},
    "worldmap":      {"runner": "claude", "model": "sonnet"},
    "system":        {"runner": "claude", "model": "sonnet"},
}

# Runner class map
RUNNER_MAP: dict[RunnerType, type[AbstractRunner]] = {
    RunnerType.CLAUDE: ClaudeRunner,
    RunnerType.CLOUD:  CloudRunner,
    RunnerType.LOCAL:  LocalRunner,
}

# ─── Auto-Detection ───

_availability_cache: dict[RunnerType, bool] = {}


def _check_cloud_available(provider: Optional[str] = None) -> bool:
    """Check if cloud API keys are set."""
    providers = [provider] if provider else ["google", "groq", "openai", "anthropic"]
    env_map = {
        "google": "GOOGLE_API_KEY",
        "groq": "GROQ_API_KEY",
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
    }
    return any(os.environ.get(env_map.get(p, ""), "") for p in providers)


def _check_local_available(endpoint: Optional[str] = None) -> bool:
    """Check if local model server (Ollama) is reachable AND has models."""
    import json as _json
    url = (endpoint or "http://localhost:11434") + "/api/tags"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            if resp.status != 200:
                return False
            data = _json.loads(resp.read().decode("utf-8"))
            models = data.get("models", [])
            return len(models) > 0  # Server up AND has at least 1 model
    except (urllib.error.URLError, OSError, TimeoutError, ValueError):
        return False


def detect_available_runners(
    provider: Optional[str] = None,
    endpoint: Optional[str] = None,
    force_refresh: bool = False,
) -> dict[RunnerType, bool]:
    """
    Detect which runners are currently available.
    Results are cached until force_refresh=True.
    """
    global _availability_cache

    if not force_refresh and _availability_cache:
        return _availability_cache

    _availability_cache = {
        RunnerType.CLAUDE: True,  # Always available (built-in)
        RunnerType.CLOUD: _check_cloud_available(provider),
        RunnerType.LOCAL: _check_local_available(endpoint),
    }
    return _availability_cache


# ─── Config Loading ───

def load_agent_config() -> dict[AgentType, AgentConfig]:
    """
    Load agent configuration from data/agent_config.json.
    Falls back to DEFAULT_CONFIG if file doesn't exist.
    """
    raw: dict[str, dict] = DEFAULT_CONFIG.copy()

    if os.path.isfile(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            user_config = json.load(f)
        # Skip non-agent keys (like _comment, _auto_detect)
        for k, v in user_config.items():
            if not k.startswith("_") and isinstance(v, dict):
                raw[k] = v

    configs: dict[AgentType, AgentConfig] = {}
    for agent_key, cfg in raw.items():
        try:
            agent_type = AgentType(agent_key)
        except ValueError:
            continue

        # Parse fallback list
        fallback_raw = cfg.get("fallback", ["claude"])
        fallback = []
        for fb in fallback_raw:
            try:
                fallback.append(RunnerType(fb))
            except ValueError:
                continue
        if not fallback:
            fallback = [RunnerType.CLAUDE]

        configs[agent_type] = AgentConfig(
            agent_type=agent_type,
            runner=RunnerType(cfg.get("runner", "claude")),
            model=cfg.get("model"),
            provider=cfg.get("provider"),
            endpoint=cfg.get("endpoint"),
            temperature=cfg.get("temperature", 0.7),
            max_tokens=cfg.get("max_tokens", 4096),
            system_prompt_path=cfg.get("system_prompt_path"),
            fallback=fallback,
        )

    return configs


# ─── Registry ───

class AgentRegistry:
    """
    Central registry for agent runners.
    Supports auto-detection and fallback chains.

    Auto-detect mode (default):
      On first dispatch, checks which runners are available.
      If the configured runner is unavailable, falls through the fallback chain.

    Manual mode:
      Set auto_detect=False to skip availability checks and use configured runner only.
    """

    def __init__(
        self,
        config: Optional[dict[AgentType, AgentConfig]] = None,
        auto_detect: bool = True,
    ):
        self.config = config or load_agent_config()
        self.auto_detect = auto_detect
        self._runners: dict[tuple[AgentType, RunnerType], AbstractRunner] = {}
        self._available: Optional[dict[RunnerType, bool]] = None
        self._fallback_log: list[dict] = []  # Track fallback events

    def _ensure_availability(self) -> dict[RunnerType, bool]:
        """Lazy-load runner availability."""
        if self._available is None:
            if self.auto_detect:
                # Collect unique providers/endpoints for detection
                providers = set()
                endpoints = set()
                for cfg in self.config.values():
                    if cfg.provider:
                        providers.add(cfg.provider)
                    if cfg.endpoint:
                        endpoints.add(cfg.endpoint)
                self._available = detect_available_runners(
                    provider=next(iter(providers), None),
                    endpoint=next(iter(endpoints), None),
                )
            else:
                # Manual mode: assume all available
                self._available = {rt: True for rt in RunnerType}
        return self._available

    # Default models per runner type (used when fallback runner differs from primary)
    FALLBACK_MODELS: dict[RunnerType, dict[str, str]] = {
        RunnerType.CLOUD: {
            "groq": "llama-3.3-70b-versatile",
            "google": "gemini-2.0-flash",
            "openai": "gpt-4o-mini",
            "anthropic": "claude-haiku-4-5-20251001",
        },
        RunnerType.LOCAL: {
            "default": "llama3",
        },
        RunnerType.CLAUDE: {
            "default": "sonnet",
        },
    }

    def _get_or_create_runner(
        self, agent_type: AgentType, runner_type: RunnerType
    ) -> AbstractRunner:
        """Get or create a runner instance. Adjusts model for fallback runners."""
        key = (agent_type, runner_type)
        if key not in self._runners:
            cfg = self.config.get(agent_type, AgentConfig(agent_type=agent_type))

            # If runner_type differs from config's primary runner,
            # override model to a sensible default for the fallback runner
            if runner_type != cfg.runner:
                fallback_models = self.FALLBACK_MODELS.get(runner_type, {})
                provider = cfg.provider or "default"
                default_model = fallback_models.get(provider) or fallback_models.get("default")
                if default_model:
                    cfg = cfg.model_copy(update={"model": default_model})

            runner_cls = RUNNER_MAP.get(runner_type, ClaudeRunner)
            self._runners[key] = runner_cls(cfg)
        return self._runners[key]

    def _resolve_runner(self, agent_type: AgentType) -> tuple[RunnerType, AbstractRunner]:
        """
        Resolve the best available runner for an agent type.
        Tries primary runner first, then fallback chain.
        """
        cfg = self.config.get(agent_type, AgentConfig(agent_type=agent_type))
        available = self._ensure_availability()

        # Try primary runner
        if available.get(cfg.runner, False):
            return cfg.runner, self._get_or_create_runner(agent_type, cfg.runner)

        # Primary unavailable — try fallback chain
        for fb_runner in cfg.fallback:
            if fb_runner != cfg.runner and available.get(fb_runner, False):
                self._fallback_log.append({
                    "agent": agent_type.value,
                    "primary": cfg.runner.value,
                    "fallback_to": fb_runner.value,
                    "reason": f"{cfg.runner.value} unavailable",
                })
                return fb_runner, self._get_or_create_runner(agent_type, fb_runner)

        # All fallbacks exhausted — claude is always available
        if cfg.runner != RunnerType.CLAUDE:
            self._fallback_log.append({
                "agent": agent_type.value,
                "primary": cfg.runner.value,
                "fallback_to": "claude",
                "reason": "all runners unavailable",
            })
        return RunnerType.CLAUDE, self._get_or_create_runner(agent_type, RunnerType.CLAUDE)

    def dispatch(self, request: AgentRequest) -> AgentResponse:
        """
        Dispatch a request to the best available runner.
        Auto-fallback if primary runner fails.
        """
        runner_type, runner = self._resolve_runner(request.agent_type)
        response = runner.run(request)

        # If execution failed and we haven't exhausted fallbacks, try next
        if not response.success and runner_type != RunnerType.CLAUDE:
            cfg = self.config.get(
                request.agent_type,
                AgentConfig(agent_type=request.agent_type),
            )
            first_error = response.errors[0] if response.errors else "unknown"

            for fb_runner in cfg.fallback:
                if fb_runner != runner_type:
                    self._fallback_log.append({
                        "agent": request.agent_type.value,
                        "primary": runner_type.value,
                        "fallback_to": fb_runner.value,
                        "reason": f"execution failed: {first_error[:100]}",
                    })
                    fb_instance = self._get_or_create_runner(
                        request.agent_type, fb_runner
                    )
                    response = fb_instance.run(request)
                    if response.success:
                        break

        return response

    def dispatch_claude_prompt(self, request: AgentRequest) -> str:
        """
        For Claude runner: return the prompt string instead of executing.
        Use this when the main Claude session calls Agent tool manually.
        Falls back to ClaudeRunner regardless of config.
        """
        runner = self._get_or_create_runner(request.agent_type, RunnerType.CLAUDE)
        return runner.build_prompt(request)

    def get_config_summary(self) -> dict[str, str]:
        """Return human-readable config summary with availability info."""
        available = self._ensure_availability()
        summary = {}
        for agent_type, cfg in self.config.items():
            label = f"{cfg.runner.value}"
            if cfg.provider:
                label += f"/{cfg.provider}"
            if cfg.model:
                label += f" ({cfg.model})"

            # Mark availability
            is_available = available.get(cfg.runner, False)
            if not is_available:
                fb_names = [fb.value for fb in cfg.fallback if available.get(fb, False)]
                fb_str = fb_names[0] if fb_names else "claude"
                label += f" [unavailable → {fb_str}]"

            summary[agent_type.value] = label
        return summary

    def get_fallback_log(self) -> list[dict]:
        """Return log of fallback events (for debugging/display)."""
        return self._fallback_log.copy()

    def refresh_availability(self) -> dict[RunnerType, bool]:
        """Force re-check of runner availability."""
        self._available = None
        return self._ensure_availability()
