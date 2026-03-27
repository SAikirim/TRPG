"""
Local Runner — local model backend (Ollama, llama.cpp server, etc.)
Connects to a locally running LLM via HTTP API.
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error
from typing import Any

from core.schemas.base import (
    AgentConfig,
    AgentRequest,
    AgentResponse,
    RunnerType,
)
from core.runners.base import AbstractRunner


class LocalRunner(AbstractRunner):
    """
    Runner for locally hosted models.
    Default: Ollama API at http://localhost:11434

    Config:
      endpoint: API base URL (default: http://localhost:11434)
      model: Model name (default: llama3)
    """

    runner_type = RunnerType.LOCAL

    def _get_endpoint(self) -> str:
        return self.config.endpoint or "http://localhost:11434"

    def execute(self, request: AgentRequest) -> AgentResponse:
        """Execute via local Ollama-compatible API."""
        endpoint = self._get_endpoint()
        model = self.config.model or "llama3"
        prompt = self.build_prompt(request)

        url = f"{endpoint}/api/generate"
        body = json.dumps({
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": self.config.temperature,
                "num_predict": self.config.max_tokens,
            },
        }).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode("utf-8"))

            raw_output = result.get("response", "")
            return self._parse_output(raw_output, request)

        except urllib.error.URLError as e:
            return AgentResponse(
                agent_type=request.agent_type,
                success=False,
                errors=[
                    f"Local model connection failed ({endpoint}): {str(e)}. "
                    f"Is Ollama running? Try: ollama serve"
                ],
            )
        except json.JSONDecodeError as e:
            return AgentResponse(
                agent_type=request.agent_type,
                success=False,
                errors=[f"Invalid response from local model: {str(e)}"],
            )

    def _parse_output(
        self, raw: str, request: AgentRequest
    ) -> AgentResponse:
        """Parse JSON output from local model."""
        try:
            payload = json.loads(raw)
            return AgentResponse(
                agent_type=request.agent_type,
                success=True,
                payload=payload,
                warnings=payload.pop("warnings", []) if isinstance(payload, dict) else [],
            )
        except json.JSONDecodeError:
            # Local models sometimes wrap JSON in text
            for marker in ["```json", "```"]:
                if marker in raw:
                    try:
                        json_str = raw.split(marker)[1].split("```")[0].strip()
                        payload = json.loads(json_str)
                        return AgentResponse(
                            agent_type=request.agent_type,
                            success=True,
                            payload=payload,
                        )
                    except (json.JSONDecodeError, IndexError):
                        continue

            return AgentResponse(
                agent_type=request.agent_type,
                success=False,
                payload={"raw_output": raw[:2000]},
                errors=["Failed to parse JSON from local model output"],
            )
