"""
Agent Session Manager — maintains conversation history per agent.
First call: full context (files + rules). Subsequent calls: delta only.
Reduces token usage by ~60-70% after the first turn.
"""

from __future__ import annotations

import threading
from typing import Any, Optional

from core.schemas.base import AgentType


class TokenUsage:
    """Tracks cumulative token usage per agent."""

    def __init__(self):
        self.prompt_tokens: int = 0
        self.completion_tokens: int = 0
        self.total_tokens: int = 0
        self.call_count: int = 0

    def add(self, prompt: int, completion: int, total: int) -> None:
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.total_tokens += total
        self.call_count += 1

    def to_dict(self) -> dict:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "calls": self.call_count,
        }


class AgentSession:
    """Single agent's conversation history + token tracking."""

    def __init__(self, agent_type: AgentType, system_prompt: str):
        self.agent_type = agent_type
        self.system_prompt = system_prompt
        self.messages: list[dict[str, str]] = []
        self.initialized = False  # True after first full-context call
        self.turn_count = 0
        self.usage = TokenUsage()

    def add_user(self, content: str) -> None:
        self.messages.append({"role": "user", "content": content})

    def add_assistant(self, content: str) -> None:
        self.messages.append({"role": "assistant", "content": content})

    def get_messages(self) -> list[dict[str, str]]:
        """Return full message list for API call (system + history)."""
        return [{"role": "system", "content": self.system_prompt}] + self.messages

    def trim(self, max_messages: int = 20) -> None:
        """Keep last N messages to prevent context overflow."""
        if len(self.messages) > max_messages:
            # Keep first 2 (initial context) + last (max-2) messages
            self.messages = self.messages[:2] + self.messages[-(max_messages - 2):]

    def reset(self) -> None:
        self.messages.clear()
        self.initialized = False
        self.turn_count = 0


class SessionManager:
    """
    Manages sessions for all agents. Thread-safe.

    Usage:
        sm = SessionManager()
        session = sm.get_or_create(AgentType.NPC, system_prompt)
        if not session.initialized:
            # First call: include full file context
            session.add_user(full_context_prompt)
            session.initialized = True
        else:
            # Subsequent calls: delta only
            session.add_user(delta_prompt)
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._sessions: dict[AgentType, AgentSession] = {}

    def get_or_create(self, agent_type: AgentType, system_prompt: str) -> AgentSession:
        with self._lock:
            if agent_type not in self._sessions:
                self._sessions[agent_type] = AgentSession(agent_type, system_prompt)
            return self._sessions[agent_type]

    def get(self, agent_type: AgentType) -> Optional[AgentSession]:
        return self._sessions.get(agent_type)

    def reset(self, agent_type: AgentType) -> None:
        with self._lock:
            if agent_type in self._sessions:
                self._sessions[agent_type].reset()

    def reset_all(self) -> None:
        with self._lock:
            for s in self._sessions.values():
                s.reset()

    def status(self) -> dict[str, dict]:
        return {
            at.value: {
                "initialized": s.initialized,
                "messages": len(s.messages),
                "turns": s.turn_count,
                "tokens": s.usage.to_dict(),
            }
            for at, s in self._sessions.items()
        }

    def total_usage(self) -> dict:
        """Aggregate token usage across all agents."""
        total = TokenUsage()
        for s in self._sessions.values():
            total.prompt_tokens += s.usage.prompt_tokens
            total.completion_tokens += s.usage.completion_tokens
            total.total_tokens += s.usage.total_tokens
            total.call_count += s.usage.call_count
        return total.to_dict()
