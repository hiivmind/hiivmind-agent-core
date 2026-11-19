"""The LangGraph backend. A fresh agent is built for each unit, so a run's state lives in graph state and its checkpoint,
never on the backend (KIT-1)."""

import os
from collections.abc import Mapping
from pathlib import Path

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage

from agent_core.backends.langgraph.hook import PolicyHook, text_of
from agent_core.backends.langgraph.matrix import FEATURES
from agent_core.backends.langgraph.providers import provider_module
from agent_core.backends.langgraph.settings import LangGraphSettings
from agent_core.backends.langgraph.tools import _render, sdk_tools
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
        policy = await unit.start(unit.name, unit.inputs)
        if isinstance(policy, UnitResult):   # the node did not start
            return policy
        module, name = self._provider, self._model
        agent = create_agent(
            module.chat_model(name, self._settings),
            tools=sdk_tools(policy, unit.tools),
            system_prompt=policy.instructions,
            # Task 5 puts the retry middleware (`ModelRetryMiddleware`, the one retry owner) before the hook.
            middleware=[*module.cache_middleware(), PolicyHook(policy, module, unit.events)],
        )
        messages = _render(policy.handover)
        if policy.opening:   # a run started again ends its hand-over with a call and its result: no opening then
            messages.append(HumanMessage(policy.opening))
        config = {"recursion_limit": self._settings.RECURSION_LIMIT, "configurable": {"thread_id": unit.thread}}
        state = await agent.ainvoke({"messages": messages, "node": policy.initial()}, config=config)
        last = state["messages"][-1]
        said = text_of(last) if isinstance(last, AIMessage) and not last.tool_calls else ""
        return policy.finish(state["node"], said)

    async def run_fragment(self, unit: Unit) -> UnitResult:
        raise NotImplementedError("task 9")

    async def close(self) -> None:
        pass
