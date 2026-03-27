"""
Cloud Runner — external API backend (Gemini, Groq, OpenAI, etc.)
Sends AgentRequest as a structured prompt to cloud LLM APIs.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

from core.schemas.base import (
    AgentConfig,
    AgentRequest,
    AgentResponse,
    RunnerType,
)
from core.runners.base import AbstractRunner


# ─── Multi-Key Rotation ───

class KeyRotator:
    """
    Round-robin API key rotation for rate limit distribution.
    Reads GROQ_API_KEY, GROQ_API_KEY_2, GROQ_API_KEY_3, ... from env.
    Thread-safe.
    """

    def __init__(self, provider: str):
        self._lock = threading.Lock()
        self._keys: list[str] = []
        self._index = 0

        env_prefix = f"{provider.upper()}_API_KEY"
        # Primary key
        primary = os.environ.get(env_prefix, "")
        if primary:
            self._keys.append(primary)
        # Additional keys: _2, _3, _4, ...
        for i in range(2, 10):
            key = os.environ.get(f"{env_prefix}_{i}", "")
            if key:
                self._keys.append(key)

    @property
    def count(self) -> int:
        return len(self._keys)

    def next_key(self) -> str:
        if not self._keys:
            raise EnvironmentError("No API keys found")
        with self._lock:
            key = self._keys[self._index % len(self._keys)]
            self._index += 1
            return key


# Global rotators (one per provider, lazy-initialized)
_rotators: dict[str, KeyRotator] = {}
_rotator_lock = threading.Lock()


def _get_rotator(provider: str) -> KeyRotator:
    with _rotator_lock:
        if provider not in _rotators:
            _rotators[provider] = KeyRotator(provider)
        return _rotators[provider]


class CloudRunner(AbstractRunner):
    """
    Runner for cloud-hosted LLM APIs.
    Supports: google (Gemini), groq (Llama/Mixtral), openai (GPT), anthropic (Claude).

    Session support: maintains conversation history per agent.
    First call sends full file context, subsequent calls send delta only.

    Multi-key rotation: set GROQ_API_KEY, GROQ_API_KEY_2, GROQ_API_KEY_3
    to distribute requests across multiple keys for higher rate limits.
    """

    runner_type = RunnerType.CLOUD

    def __init__(self, config):
        super().__init__(config)
        from core.runners.session import SessionManager
        # Shared session manager (class-level singleton)
        if not hasattr(CloudRunner, '_session_mgr'):
            CloudRunner._session_mgr = SessionManager()
        self.sessions: SessionManager = CloudRunner._session_mgr

    def _get_api_key(self) -> str:
        provider = self.config.provider or "google"
        rotator = _get_rotator(provider)
        if rotator.count > 0:
            return rotator.next_key()
        # Fallback to single key
        env_map = {
            "google": "GOOGLE_API_KEY",
            "groq": "GROQ_API_KEY",
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
        }
        key_name = env_map.get(provider, f"{provider.upper()}_API_KEY")
        key = os.environ.get(key_name, "")
        if not key:
            raise EnvironmentError(
                f"API key not found: set {key_name} environment variable"
            )
        return key

    def execute(self, request: AgentRequest) -> AgentResponse:
        """Execute via cloud API. Provider-specific dispatch."""
        provider = self.config.provider or "google"

        if provider == "google":
            return self._execute_gemini(request)
        elif provider == "groq":
            return self._execute_groq(request)
        elif provider == "openai":
            return self._execute_openai(request)
        elif provider == "anthropic":
            return self._execute_anthropic(request)
        else:
            return AgentResponse(
                agent_type=request.agent_type,
                success=False,
                errors=[f"Unknown cloud provider: {provider}"],
            )

    def _execute_gemini(self, request: AgentRequest) -> AgentResponse:
        """Google Gemini API call."""
        try:
            import google.generativeai as genai
        except ImportError:
            return AgentResponse(
                agent_type=request.agent_type,
                success=False,
                errors=["google-generativeai package not installed: pip install google-generativeai"],
            )

        api_key = self._get_api_key()
        genai.configure(api_key=api_key)

        model = genai.GenerativeModel(self.config.model or "gemini-1.5-flash")
        prompt = self.build_prompt(request)

        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                temperature=self.config.temperature,
                max_output_tokens=self.config.max_tokens,
                response_mime_type="application/json",
            ),
        )

        return self._parse_llm_output(response.text, request)

    def _execute_groq(self, request: AgentRequest) -> AgentResponse:
        """Groq API call with session support."""
        try:
            from groq import Groq
        except ImportError:
            return AgentResponse(
                agent_type=request.agent_type,
                success=False,
                errors=["groq package not installed: pip install groq"],
            )

        from core.runners.base import AGENT_PROMPTS

        client = Groq(api_key=self._get_api_key())

        # Get or create session for this agent
        system_prompt = AGENT_PROMPTS.get(
            request.agent_type,
            f"You are the [{request.agent_type.value}] agent."
        )
        system_prompt += "\nYou are a TRPG agent. Respond only with valid JSON."
        session = self.sessions.get_or_create(request.agent_type, system_prompt)

        if not session.initialized:
            # First call: full context with file data
            full_prompt = self.build_prompt(request)
            session.add_user(full_prompt)
            session.initialized = True
        else:
            # Subsequent calls: delta only (no file re-read)
            import json as _json
            ctx = request.context
            delta = (
                f"Turn: {ctx.turn_number} | Location: {ctx.current_location} | Time: {ctx.time_of_day}\n"
                f"GM Direction: {ctx.gm_direction}\n"
                f"Players: {_json.dumps(ctx.player_summary, ensure_ascii=False)}\n"
                f"NPCs: {_json.dumps(ctx.npc_summary, ensure_ascii=False)}\n\n"
                f"Request:\n{_json.dumps(request.payload, ensure_ascii=False, indent=2)}\n\n"
                f"Return ONLY valid JSON matching your response schema. Include the \"narration\" key."
            )
            session.add_user(delta)

        messages = session.get_messages()
        session.turn_count += 1

        response = client.chat.completions.create(
            model=self.config.model or "llama-3.3-70b-versatile",
            messages=messages,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content
        # Save assistant response to session history
        session.add_assistant(raw)
        session.trim(max_messages=20)

        # Track token usage
        if response.usage:
            session.usage.add(
                prompt=response.usage.prompt_tokens,
                completion=response.usage.completion_tokens,
                total=response.usage.total_tokens,
            )

        return self._parse_llm_output(raw, request)

    def _execute_openai(self, request: AgentRequest) -> AgentResponse:
        """OpenAI API call."""
        try:
            from openai import OpenAI
        except ImportError:
            return AgentResponse(
                agent_type=request.agent_type,
                success=False,
                errors=["openai package not installed: pip install openai"],
            )

        client = OpenAI(api_key=self._get_api_key())
        prompt = self.build_prompt(request)

        response = client.chat.completions.create(
            model=self.config.model or "gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Respond only with valid JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            response_format={"type": "json_object"},
        )

        return self._parse_llm_output(
            response.choices[0].message.content, request
        )

    def _execute_anthropic(self, request: AgentRequest) -> AgentResponse:
        """Anthropic Claude API call."""
        try:
            from anthropic import Anthropic
        except ImportError:
            return AgentResponse(
                agent_type=request.agent_type,
                success=False,
                errors=["anthropic package not installed: pip install anthropic"],
            )

        client = Anthropic(api_key=self._get_api_key())
        prompt = self.build_prompt(request)

        response = client.messages.create(
            model=self.config.model or "claude-haiku-4-5-20251001",
            max_tokens=self.config.max_tokens,
            messages=[
                {"role": "user", "content": prompt + "\n\nRespond ONLY with valid JSON."},
            ],
        )

        raw = response.content[0].text
        return self._parse_llm_output(raw, request)

    def _parse_llm_output(
        self, raw: str, request: AgentRequest
    ) -> AgentResponse:
        """Parse JSON output from any cloud LLM."""
        try:
            payload = json.loads(raw)
            return AgentResponse(
                agent_type=request.agent_type,
                success=True,
                payload=payload,
                warnings=payload.pop("warnings", []) if isinstance(payload, dict) else [],
            )
        except json.JSONDecodeError as e:
            return AgentResponse(
                agent_type=request.agent_type,
                success=False,
                payload={"raw_output": raw[:2000]},
                errors=[f"JSON parse error from {self.config.provider}: {str(e)}"],
            )
