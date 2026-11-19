"""The brief's tools and hand-over as SDK objects.

Each tool the policy offers is an SDK tool whose body calls `policy.call` over the node state the graph holds, and returns
a `Command` that writes the call's update to the `node` channel together with the call's `ToolMessage`. `ToolNode`
applies the updates when its step ends, so every call of a response reads the state as it was before the response (CTL-5).
"""

from dataclasses import asdict

from langchain.tools import ToolRuntime
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.types import Command

from agent_core.contracts.policy import Policy
from agent_core.contracts.unit import DeclaredTools
from agent_core.contracts.values import Message, ToolCall, ToolSpec


def _render(handover: tuple[Message, ...]) -> list:
    """What a strategy handed over, as the messages of a conversation."""
    messages: list = []
    for item in handover:
        if item.kind == "user":
            messages.append(HumanMessage(item.text))
        elif item.kind == "agent":
            messages.append(AIMessage(item.text))
        else:
            call = {"id": item.call_id, "name": item.name, "args": item.args, "type": "tool_call"}
            messages += [AIMessage(content=item.text, tool_calls=[call]), ToolMessage(item.result, tool_call_id=item.call_id, name=item.name)]
    return messages


def _tool(policy: Policy, spec: ToolSpec) -> BaseTool:
    async def run(runtime: ToolRuntime, **args) -> Command:
        result = await policy.call(ToolCall(runtime.tool_call_id, spec.name, args), runtime.state["node"])
        message = ToolMessage(result.text, tool_call_id=runtime.tool_call_id, name=spec.name, status="error" if result.error else "success")
        update: dict = {"messages": [message]}
        if result.update is not None:
            update["node"] = {"update": asdict(result.update)}
        return Command(update=update)

    return StructuredTool(name=spec.name, description=spec.description, args_schema=spec.schema, coroutine=run)


def sdk_tools(policy: Policy, declared: DeclaredTools) -> list[BaseTool]:
    """One SDK tool for each tool the policy offers: the verbs, the function tools and the server tools."""
    return [_tool(policy, spec) for spec in policy.tools]
