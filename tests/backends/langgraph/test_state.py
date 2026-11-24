"""Node state in the graph's `node` channel, and the verbs and function tools as SDK tools whose bodies call core policy."""

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, ToolMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "conformance"))
from script_model import ScriptChatModel, ScriptProvider  # noqa: E402

from agent_core.backends.langgraph.backend import LangGraphBackend  # noqa: E402
from agent_core.backends.langgraph.hook import PolicyHook  # noqa: E402
from agent_core.backends.langgraph.settings import LangGraphSettings  # noqa: E402
from agent_core.backends.langgraph.tools import sdk_tools  # noqa: E402
from agent_core.contracts.policy import CallResult, Ending, Review, StateUpdate  # noqa: E402
from agent_core.contracts.unit import DeclaredTools, Unit, UnitResult  # noqa: E402
from agent_core.contracts.values import ToolSpec  # noqa: E402
from agent_core.core.policy import VERBS, NodePolicy, verb_spec  # noqa: E402
from agent_core.core.functions import FunctionTool  # noqa: E402

SPECS = {v.name: verb_spec(v) for v in VERBS}

SCHEMA = {"type": "object", "properties": {"key": {"type": "string"}, "value": {}}}


class Events:
    def __init__(self):
        self.seen = []

    def emit(self, event):
        self.seen.append(event)


class StatePolicy:
    """`set` writes a value, `get` reads one, `boom` fails after meaning to write, `exit` ends. Records what ran."""

    node, opening, handover = "n", "go", ()
    instructions = "# Procedure of the node that is running: `n`\n"
    tools = tuple(ToolSpec(name, name, SCHEMA) for name in ("set", "get", "boom", "exit"))

    def __init__(self, label="t", who="x"):
        self.label, self.who, self.ran, self.read = label, who, [], []

    def initial(self):
        return {"inputs": {}, "values": {"who": self.who}, "outputs": {}, "session": {}, "rejections": 0, "ending": None}

    def review(self, response, state):
        return Review({})

    async def call(self, call, state):
        self.ran.append(call.name)
        await asyncio.sleep(0)   # let a sibling unit run between the calls
        if call.name == "set":
            return CallResult(f"recorded {call.args['key']}", update=StateUpdate(values={call.args["key"]: call.args["value"]}))
        if call.name == "get":
            self.read.append(state["values"].get(call.args["key"], "not set"))
            return CallResult(json.dumps(self.read[-1]))
        if call.name == "boom":
            return CallResult("error: boom", error=True)   # a failed call carries no update
        return CallResult("exited", update=StateUpdate(ending=Ending("done", {"who": state["values"]["who"]})))

    def stopped(self, said, state):
        return None

    def finish(self, state, said):
        return UnitResult(state["ending"]["outcome"], {**state["values"], **state["ending"]["outputs"]})


class Spy(ScriptChatModel):
    """Keeps the tools the agent binds it with."""

    bound: list = []

    def bind_tools(self, tools, **kwargs):
        Spy.bound = list(tools)
        return super().bind_tools(tools, **kwargs)


async def play(tmp_path, steps, policy=None, model=ScriptChatModel):
    (tmp_path / "n.json").write_text(json.dumps(steps))
    policy = policy or StatePolicy()
    agent = create_agent(
        model(directory=tmp_path), tools=sdk_tools(policy, None), system_prompt=policy.instructions,
        middleware=[PolicyHook(policy, ScriptProvider(), Events())],
    )
    config = {"recursion_limit": 30, "metadata": {"agent_core_node": "n"}}   # as the backend's run config names it (CD-13)
    state = await agent.ainvoke({"messages": [HumanMessage("go")], "node": policy.initial()}, config=config)
    return policy, state


def texts(state, name):
    return [m.content for m in state["messages"] if isinstance(m, ToolMessage) and m.name == name]


async def test_each_call_of_a_response_sees_the_state_before_it(tmp_path):   # CTL-5
    steps = [
        [["set", {"key": "c", "value": "red"}], ["get", {"key": "c"}]],
        [["get", {"key": "c"}]],
        [["exit", {}]],
    ]
    policy, state = await play(tmp_path, steps)
    assert texts(state, "get") == ['"not set"', '"red"']
    assert state["node"]["values"]["c"] == "red"


def _writes_then_raises(state):
    state["leaked"] = "sentinel"   # a write the failing function made before it raised
    raise RuntimeError("after writing")


def _writes_a(state):
    state["a"] = 1
    return "ok"


def _writes_b(state):
    state["b"] = 2
    return "ok"


def _real_policy(*functions):
    """A real `NodePolicy`, offering `state_set`, `state_get` and these functions (each filled with `state`)."""
    contract = SimpleNamespace(name="n", inputs={}, outputs={})
    tools = {f.__name__: FunctionTool(f.__name__, ToolSpec(f.__name__, f.__name__, {"type": "object"}), f, ("state",)) for f in functions}
    specs = (SPECS["state_set"], SPECS["state_get"], *(t.spec for t in tools.values()))
    start = {"inputs": {}, "values": {}, "outputs": {}, "session": {}, "rejections": 0, "ending": None}
    return NodePolicy(
        SimpleNamespace(contract=contract), number=1, instructions="The node's procedure.\n", tools=specs,
        handover=(), opening="go", functions=tools, servers=None, person=None, resources=None, settings=None, events=Events(), start=start,
    )


async def test_a_failed_calls_writes_are_dropped_and_the_others_applied_in_order(tmp_path):   # Plan 1 Review Focus 5, CTL-5
    policy = _real_policy(_writes_then_raises, _writes_a, _writes_b)
    steps = [[
        ["state_set", {"key": "c", "value": "red"}], ["_writes_then_raises", {}], ["_writes_a", {}],
        ["state_set", {"key": "c", "value": "blue"}], ["_writes_b", {}],
    ], "done"]
    policy, state = await play(tmp_path, steps, policy)
    failed = next(m for m in state["messages"] if isinstance(m, ToolMessage) and m.name == "_writes_then_raises")
    assert (failed.content, failed.status) == ("error: _writes_then_raises raised RuntimeError: after writing", "error")
    values = state["node"]["values"]
    assert "leaked" not in values                                  # what the failed function wrote is dropped
    assert values == {"c": "blue", "a": 1, "b": 2}                 # the others are applied, the later write of `c` wins
    assert list(values) == ["c", "a", "b"]                         # in the order the model gave the calls


async def test_settings_and_state_never_reach_the_model(tmp_path):   # TOOL-12
    await play(tmp_path, [[["exit", {}]]], model=Spy)
    assert {t.name for t in Spy.bound} >= {"set", "get", "exit"}
    for tool in Spy.bound:
        wire = json.dumps(tool if isinstance(tool, dict) else tool.args_schema if isinstance(tool.args_schema, dict) else tool.args)
        assert not any(word in wire for word in ("settings", "state", "runtime", "node"))


def _unit(policy, thread):
    async def start(node, inputs):
        return policy

    async def call_tool(name, args):
        raise AssertionError

    return Unit("n", {}, "start", thread, start, DeclaredTools({}, frozenset(), None), Events(), None, call_tool)


async def test_two_units_at_once_share_nothing(tmp_path, monkeypatch):   # Review Focus 3, KIT-1
    steps = [[["set", {"key": "mine", "value": "m"}]], [["get", {"key": "mine"}], ["get", {"key": "who"}]], [["exit", {}]]]
    (tmp_path / "n.json").write_text(json.dumps(steps))
    backend = LangGraphBackend(LangGraphSettings(MODEL=f"script:{tmp_path}"))
    first, second = StatePolicy("a", "first"), StatePolicy("b", "second")
    results = await asyncio.gather(backend.run_node(_unit(first, "t-a")), backend.run_node(_unit(second, "t-b")))
    assert [r.outputs["who"] for r in results] == ["first", "second"]
    assert first.ran == second.ran == ["set", "get", "get", "exit"]
    assert first.read == ["m", "first"] and second.read == ["m", "second"]   # each read its own state, and nobody else's
