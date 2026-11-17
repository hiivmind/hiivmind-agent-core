"""A NodeDriver on LangChain's agent package.

It knows no verb, holds no harness state and uses no checkpointer. Each tool it offers is a proxy: the call is
handed to the controller and the proxy's own body is never run. One instance serves any number of runs at once,
so a run's state lives in the objects `drive` makes, never on the instance.

The provider's key is read by its client from `ANTHROPIC_API_KEY`.
"""

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_anthropic import ChatAnthropic
from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool

from agent_core.contracts import Brief, EndRun, Message, ModelResponse, NodeController, RunEnd, ToolCall, ToolSpec
from agent_core.contracts.registry import register_backend

from .settings import LangGraphSettings


async def _never(**_) -> str:
    raise RuntimeError("a proxy tool's body was run; each call is the controller's to handle")


def _proxy(spec: ToolSpec) -> StructuredTool:
    return StructuredTool(name=spec.name, description=spec.description, args_schema=spec.schema, coroutine=_never)


def _render(item: Message) -> list:
    if item.kind == "user":
        return [HumanMessage(item.text)]
    if item.kind == "agent":
        return [AIMessage(item.text)]
    call = {"id": item.call_id, "name": item.name, "args": item.args, "type": "tool_call"}
    return [AIMessage(content=item.text, tool_calls=[call]), ToolMessage(item.result, tool_call_id=item.call_id)]


def _response(message: AIMessage) -> ModelResponse:
    content = message.content
    text = content if isinstance(content, str) else "".join(
        b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
    )
    usage = message.usage_metadata or {}
    details = usage.get("input_token_details") or {}
    calls = tuple(ToolCall(c["id"], c["name"], c["args"]) for c in (message.tool_calls or []))
    # The integration reports what was written to the cache under the lifetime it was written with.
    written = details.get("cache_creation") or (
        details.get("ephemeral_5m_input_tokens", 0) + details.get("ephemeral_1h_input_tokens", 0)
    )
    return ModelResponse(text, calls, usage.get("input_tokens"), details.get("cache_read"), written if details else None)


class _Relay(AgentMiddleware):
    """Puts the run's events to the controller. One is made for each run."""

    def __init__(self, controller: NodeController):
        super().__init__()
        self.controller = controller
        self.ended = False
        self.said = ""

    @hook_config(can_jump_to=["end"])
    async def abefore_model(self, state, runtime):
        return {"jump_to": "end"} if self.ended else None

    @hook_config(can_jump_to=["model"])
    async def aafter_model(self, state, runtime):
        response = _response(state["messages"][-1])
        await self.controller.responded(response)  # before any of its calls is handed over
        if response.calls:
            self.said = ""
            return None
        self.said = response.text
        told = await self.controller.stopped(response.text)
        if told is None:
            return None
        return {"messages": [HumanMessage(told)], "jump_to": "model"}  # carry on the same conversation

    async def awrap_tool_call(self, request, handler):
        call = request.tool_call
        outcome = await self.controller.handle(ToolCall(call["id"], call["name"], call["args"]))
        if isinstance(outcome, EndRun):
            self.ended = True
            return ToolMessage("(the run has ended)", tool_call_id=call["id"])
        return ToolMessage(outcome.text, tool_call_id=call["id"], status="error" if outcome.error else "success")


@register_backend("langgraph", settings=LangGraphSettings)
class LangGraphBackend:
    def __init__(self, settings: LangGraphSettings):
        self._settings = settings

    async def drive(self, brief: Brief, controller: NodeController) -> RunEnd:
        relay = _Relay(controller)
        agent = create_agent(
            ChatAnthropic(model=self._settings.MODEL, max_tokens=self._settings.MAX_TOKENS, max_retries=self._settings.MAX_RETRIES),
            tools=[_proxy(t) for t in brief.tools],
            system_prompt=brief.instructions,
            middleware=[AnthropicPromptCachingMiddleware(), relay],
        )
        # A run started again ends its hand-over with a call and its result; then there is no opening to add.
        messages = [m for item in brief.handover for m in _render(item)]
        if brief.opening:
            messages.append(HumanMessage(brief.opening))
        await agent.ainvoke({"messages": messages}, config={"recursion_limit": self._settings.RECURSION_LIMIT})
        return RunEnd(by_controller=relay.ended, said=relay.said)
