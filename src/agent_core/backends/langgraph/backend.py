"""The LangGraph backend. A fresh agent is built for each unit, so a run's state lives in graph state and its checkpoint,
never on the backend (KIT-1)."""

import asyncio
import contextvars
import dataclasses
from collections.abc import Mapping
from contextlib import AsyncExitStack
from pathlib import Path

from langchain.agents import create_agent
from langchain.agents.middleware import ModelRetryMiddleware
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables.config import var_child_runnable_config
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from agent_core.backends.langgraph.fragments import compile_fragment, fragment_result, initial_state
from agent_core.backends.langgraph.hook import PolicyHook, text_of
from agent_core.backends.langgraph.matrix import FEATURES
from agent_core.backends.langgraph.mcp import AdapterServers
from agent_core.backends.langgraph.providers import provider_module
from agent_core.backends.langgraph.settings import LangGraphSettings
from agent_core.backends.langgraph.tools import _render, sdk_tools
from agent_core.contracts.errors import ProviderRefused, ProviderUnavailable
from agent_core.contracts.matrix import Matrix
from agent_core.contracts.registry import register_backend
from agent_core.contracts.unit import Intent, Unit, UnitResult


@register_backend("langgraph", settings=LangGraphSettings)
class LangGraphBackend:
    FEATURES = FEATURES   # the matrix is the class's: it is read without making a backend, which needs a MODEL

    def __init__(self, settings: LangGraphSettings):
        self._settings = settings
        self._provider, self._model = provider_module(settings.MODEL)   # a run that cannot start is found now (MOD-3)
        check = getattr(self._provider, "check", None)   # a registered provider may have none
        if check is not None:
            check(settings)   # the provider's own startup check of its settings (credentials design §4.2)
        self._savers: dict[Path, AsyncSqliteSaver] = {}   # one checkpointer for each run directory, opened when first used
        self._open = AsyncExitStack()
        self._opening = asyncio.Lock()

    def features(self) -> Matrix:
        return self.FEATURES

    def servers(self, declared: Mapping[str, dict], root: Path, env: Mapping[str, str]) -> AdapterServers:
        return AdapterServers(declared, dict(env), root)

    async def _saver(self, run_dir: Path | None) -> AsyncSqliteSaver | None:
        """The checkpointer of a run directory, `checkpoints.sqlite` in it; none for a unit that has no run directory."""
        if run_dir is None:
            return None
        async with self._opening:
            if run_dir not in self._savers:
                run_dir.mkdir(parents=True, exist_ok=True)
                self._savers[run_dir] = await self._open.enter_async_context(
                    AsyncSqliteSaver.from_conn_string(str(run_dir / "checkpoints.sqlite"))
                )
            return self._savers[run_dir]

    @staticmethod
    async def _input(graph, config: dict, payload: dict, intent: Intent, saver: AsyncSqliteSaver | None) -> dict | None:
        """What the unit's graph is invoked with (ORC-6, §4.4a). `start` and `fresh` give the input. `continue` gives none
        when the thread has a checkpoint, and the graph resumes from it; with no checkpoint it starts the unit."""
        if intent == "continue" and saver is not None and (await graph.aget_state(config)).created_at is not None:
            return None
        return payload

    async def run_node(self, unit: Unit) -> UnitResult:
        return await self._run_node(unit, await self._saver(unit.run_dir), {"thread_id": unit.thread})

    async def _run_node(self, unit: Unit, checkpointer: AsyncSqliteSaver | bool | None, configurable: dict) -> UnitResult:
        """One node run. `checkpointer` is the run directory's, for a unit of its own; `None`, to checkpoint under the
        graph this call runs inside, as a node of a fragment does; `False`, for no checkpoint at all."""
        policy = await unit.start(unit.name, unit.inputs)
        if isinstance(policy, UnitResult):   # the node did not start
            return policy
        module, name = self._provider, self._model
        agent = create_agent(
            module.chat_model(name, self._settings),
            tools=sdk_tools(policy, unit.tools),
            system_prompt=policy.instructions,
            # The retry owner is outside the hook: each attempt sent is a request the hook reports (CTX-6, Q4). The
            # provider's middleware is inside it, nearest the model: the hook reports the request as the node built it.
            middleware=[self._retries(), PolicyHook(policy, module, unit.events), *module.middleware(self._settings)],
            checkpointer=checkpointer,
        )
        messages = _render(policy.handover)
        if policy.opening:   # a run started again ends its hand-over with a call and its result: no opening then
            messages.append(HumanMessage(policy.opening))
        config = {
            "recursion_limit": self._settings.RECURSION_LIMIT, "configurable": configurable,
            "metadata": {"agent_core_node": unit.name},   # the node that is running, for a model that needs it (CD-13)
        }
        saver = checkpointer if isinstance(checkpointer, AsyncSqliteSaver) else None
        try:
            payload = await self._input(agent, config, {"messages": messages, "node": policy.initial()}, unit.intent, saver)
            state = await agent.ainvoke(payload, config=config, **({"durability": "sync"} if saver else {}))
        except Exception as e:
            mapped = self._mapped(e)
            if mapped is e:
                raise
            raise mapped from e
        last = state["messages"][-1]
        said = text_of(last) if isinstance(last, AIMessage) and not last.tool_calls else ""
        return policy.finish(state["node"], said)
    def _retries(self) -> ModelRetryMiddleware:
        """The one retry owner (MOD-6): the client's own retries are off. What it gives up on is raised as it was."""
        module, settings = self._provider, self._settings
        return ModelRetryMiddleware(
            max_retries=settings.MAX_RETRIES, retry_on=lambda e: module.classify(e, settings) == "passes", on_failure="error",
        )

    def _mapped(self, error: Exception) -> Exception:
        """What the retry middleware raised, as the core reads it: a refusal that passes (RTY-2a) or one that will not
        (MOD-4); any other error is its own. The provider reads its errors against this backend's settings."""
        match self._provider.classify(error, self._settings):
            case "passes":
                return ProviderUnavailable(f"{type(error).__name__}: {error}")
            case "will not pass":
                return ProviderRefused(self._provider.refusal(error, self._settings))
            case _:
                return error

    async def run_fragment(self, unit: Unit) -> UnitResult:
        saver = await self._saver(unit.run_dir)

        async def run(node: str, inputs: Mapping, intent: Intent, thread: str) -> UnitResult:
            each = dataclasses.replace(unit, name=node, inputs=inputs, intent=intent, thread=thread, fragment=None)
            if intent == "start":   # inside the fragment's graph, under the fragment's thread
                return await self._run_node(each, None, {})
            # A second run of an item (`fresh`, or `continue` after a crash in it) is a graph of its own on its own thread:
            # no continuation of the first run's checkpoint (RTY-2), and checkpointed itself (§4.4a). It is started outside
            # the fragment's graph, so that it does not nest in it.
            outside = contextvars.copy_context()
            outside.run(var_child_runnable_config.set, None)
            return await asyncio.create_task(self._run_node(each, saver, {"thread_id": thread}), context=outside)

        async def begun(thread: str) -> bool:
            """Whether the thread has a checkpoint: a second run that was in flight when the process died."""
            found = await saver.aget_tuple({"configurable": {"thread_id": thread, "checkpoint_ns": ""}}) if saver else None
            return found is not None

        graph = compile_fragment(unit.fragment, unit, run, begun, saver)
        config = {"recursion_limit": self._settings.RECURSION_LIMIT, "configurable": {"thread_id": unit.thread}}
        payload = await self._input(graph, config, initial_state(unit.fragment, unit.inputs), unit.intent, saver)
        state = await graph.ainvoke(payload, config=config, **({"durability": "sync"} if saver else {}))
        return fragment_result(unit.fragment, state)

    async def close(self) -> None:
        self._savers.clear()
        await self._open.aclose()
