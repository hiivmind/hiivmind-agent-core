"""`PolicyHook`: core policy called from the SDK's hooks, and the `node` channel it adds to the agent's state."""

import copy
import json
from dataclasses import asdict
from typing import Annotated, Any

from langchain.agents.middleware import AgentMiddleware, AgentState, hook_config
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from agent_core.backends.langgraph.providers import ProviderModule
from agent_core.backends.langgraph.tools import _render
from agent_core.contracts.events import EventSink, ModelRequested, ModelResponded, RequestPart, ToolReturned
from agent_core.contracts.policy import Ending, NodeState, Policy, StateUpdate, merge
from agent_core.contracts.values import Message, ModelResponse, ToolCall


def reduce_node(current: NodeState | None, update: dict) -> NodeState:
    """A whole `NodeState` is the start; `{"update": asdict(StateUpdate)}` is merged into the current one."""
    if "update" not in update:
        return copy.deepcopy(update)   # type: ignore[arg-type]
    fields = dict(update["update"])
    ending = fields.get("ending")
    fields["ending"] = Ending(**ending) if ending is not None else None
    return merge(current, StateUpdate(**fields))   # type: ignore[arg-type]


class NodeAgentState(AgentState):
    node: Annotated[NodeState, reduce_node]


def text_of(message: AIMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")


class PolicyHook(AgentMiddleware):
    state_schema = NodeAgentState

    def __init__(self, policy: Policy, module: ProviderModule, events: EventSink):
        super().__init__()
        self._policy = policy
        self._module = module
        self._events = events

    def _response(self, message: AIMessage) -> ModelResponse:
        calls = tuple(ToolCall(c["id"], c["name"], c["args"]) for c in message.tool_calls)
        return ModelResponse(text_of(message), calls, self._module.usage(message))

    async def awrap_model_call(self, request, handler):
        self._events.emit(ModelRequested(self._policy.label, self._parts(request)))
        return await handler(request)

    def _parts(self, request) -> tuple[RequestPart, ...]:
        """What the model is sent: the instructions, the tools, what the strategy handed over, the conversation (CTX-6)."""
        tools = json.dumps([
            {"name": t.name, "description": t.description, "schema": t.args_schema if isinstance(t.args_schema, dict) else t.args}
            for t in request.tools
        ])
        held = len(_render(self._policy.handover))
        handed, rest = request.messages[:held], request.messages[held:]
        return (
            RequestPart("instructions", text=request.system_message.text if request.system_message else ""),
            RequestPart("tools", text=tools),
            *((RequestPart("hand-over", messages=_conversation(handed)),) if self._policy.handover else ()),
            RequestPart("conversation", messages=_conversation(rest)),
        )

    @hook_config(can_jump_to=["end"])
    async def abefore_model(self, state, runtime):
        return {"jump_to": "end"} if state["node"]["ending"] is not None else None   # KIT-6, CTL-7

    @hook_config(can_jump_to=["model"])
    async def aafter_model(self, state, runtime):
        response = self._response(state["messages"][-1])
        self._events.emit(ModelResponded(self._policy.label, response))   # before any of its calls runs
        if response.calls:
            return None
        told = self._policy.stopped(response.text, state["node"])
        if told is None:
            return None
        return {"messages": [HumanMessage(told)], "jump_to": "model"}   # carry on the same conversation (KIT-10)

    async def awrap_tool_call(self, request, handler):
        call = request.tool_call
        last = next(m for m in reversed(request.state["messages"]) if isinstance(m, AIMessage))
        review = self._policy.review(self._response(last), request.state["node"])   # the whole response, every time
        if call["id"] in review.refused:
            result = ToolMessage(review.refused[call["id"]], tool_call_id=call["id"], name=call["name"], status="error")
        else:
            result = await handler(request)
        self._events.emit(ToolReturned(self._policy.label, ToolCall(call["id"], call["name"], call["args"]), *_returned(result)))
        return result


def _returned(result: ToolMessage | Command) -> tuple[str, bool]:
    message = result if isinstance(result, ToolMessage) else result.update["messages"][0]
    return str(message.content), message.status == "error"


def _conversation(messages) -> tuple[Message, ...]:
    """LangChain messages as neutral ones: a call and its result are one `call` message."""
    results = {m.tool_call_id: str(m.content) for m in messages if isinstance(m, ToolMessage)}
    out: list[Message] = []
    for m in messages:
        if isinstance(m, HumanMessage):
            out.append(Message("user", str(m.content)))
        elif isinstance(m, AIMessage):
            if not m.tool_calls or text_of(m):   # the text is kept once, before its calls
                out.append(Message("agent", text_of(m)))
            for c in m.tool_calls:
                out.append(Message("call", call_id=c["id"], name=c["name"], args=c["args"], result=results.get(c["id"], "")))
    return tuple(out)
