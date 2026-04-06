"""
Runner abstraction layer — pluggable agent execution backends.
Same pydantic schemas, different execution engines.
"""

from core.runners.base import AbstractRunner
from core.runners.registry import AgentRegistry, load_agent_config

__all__ = ["AbstractRunner", "AgentRegistry", "load_agent_config"]
