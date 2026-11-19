"""The LangGraph backend. A fresh agent is built for each unit, so a run's state lives in graph state and its checkpoint,
never on the backend (KIT-1)."""

import os
from collections.abc import Mapping
from pathlib import Path

from agent_core.backends.langgraph.matrix import FEATURES
from agent_core.backends.langgraph.providers import provider_module
from agent_core.backends.langgraph.settings import LangGraphSettings
from agent_core.contracts.matrix import Matrix
from agent_core.contracts.registry import register_backend
from agent_core.contracts.unit import Unit, UnitResult
from agent_core.helpers.mcp import McpServers


@register_backend("langgraph", settings=LangGraphSettings)
class LangGraphBackend:
    FEATURES = FEATURES   # the matrix is the class's: it is read without making a backend, which needs a MODEL

    def __init__(self, settings: LangGraphSettings):
        self._settings = settings
        self._provider, self._model = provider_module(settings.MODEL)   # a run that cannot start is found now (MOD-3)

    def features(self) -> Matrix:
        return self.FEATURES

    def servers(self, declared: Mapping[str, dict], root: Path) -> McpServers:
        return McpServers(declared, dict(os.environ), root)   # the environment as it is now: the facade has just set it

    async def run_node(self, unit: Unit) -> UnitResult:
        raise NotImplementedError("task 2")

    async def run_fragment(self, unit: Unit) -> UnitResult:
        raise NotImplementedError("task 9")

    async def close(self) -> None:
        pass
