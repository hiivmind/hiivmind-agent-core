"""`PolicyHook` over a small policy of the test's own: what it passes to the tool bodies, and when it stops the model."""

import json
import sys
from pathlib import Path

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, ToolMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "conformance"))
from script_model import ScriptChatModel, ScriptProvider  # noqa: E402

from agent_core.backends.langgraph.hook import PolicyHook  # noqa: E402
from agent_core.backends.langgraph.tools import sdk_tools  # noqa: E402
from agent_core.contracts.policy import CallResult, Ending, Review, StateUpdate  # noqa: E402
from agent_core.contracts.values import ToolSpec  # noqa: E402

SCHEMA = {"type": "object", "properties": {}}
ALONE = "refused: `exit` must be alone"


class Events:
    def __init__(self):
        self.seen = []

    def emit(self, event):
        self.seen.append(event)


ASKED: list = []


class Counting(ScriptChatModel):

    def _generate(self, *args, **kwargs):
        ASKED.append(1)
        return super()._generate(*args, **kwargs)


class FakePolicy:
    label, node, opening, handover = "t", "n", "go", ()
    instructions = "# Procedure of the node that is running: `n`\n"
    tools = (ToolSpec("work", "does work", SCHEMA), ToolSpec("exit", "ends", SCHEMA))

    def __init__(self):
        self.ran, self.seen = [], []

    def initial(self):
        return {"inputs": {}, "values": {}, "outputs": {}, "session": {}, "rejections": 0, "ending": None}

    def review(self, response, state):
        if len(response.calls) > 1 and any(c.name == "exit" for c in response.calls):
            return Review({c.id: ALONE for c in response.calls})
        return Review({c.id: "refused: no" for c in response.calls if c.name == "work" and c.args.get("bad")})

    async def call(self, call, state):
        self.ran.append(call.name)
        self.seen.append(("call", call.name))
        if call.name == "exit":
            return CallResult("exited", update=StateUpdate(ending=Ending("done", {})))
        return CallResult("worked")

    async def responded(self, response, state):
        self.seen.append(("responded", len(response.calls)))
        return None

    def finish(self, state, said):
        raise NotImplementedError


async def play(tmp_path, steps):
    (tmp_path / "n.json").write_text(json.dumps(steps))
    policy, events = FakePolicy(), Events()
    ASKED.clear()
    module = ScriptProvider()
    agent = create_agent(
        Counting(directory=tmp_path), tools=sdk_tools(policy, None), system_prompt=policy.instructions,
        middleware=[PolicyHook(policy, module, events)],
    )
    config = {"recursion_limit": 30, "metadata": {"agent_core_node": "n"}}   # as the backend's run config names it (CD-13)
    state = await agent.ainvoke({"messages": [HumanMessage("go")], "node": policy.initial()}, config=config)
    return policy, events, state


async def test_the_policy_sees_the_whole_response_before_any_call_runs(tmp_path):   # example 8
    policy, events, state = await play(tmp_path, [[["work", {}], ["exit", {}]], [["exit", {}]]])
    assert policy.ran == ["exit"]   # neither call of the first response ran; the second response's exit did
    refusals = [m for m in state["messages"] if isinstance(m, ToolMessage) and m.status == "error"]
    assert [m.content for m in refusals] == [ALONE, ALONE]


async def test_only_the_calls_the_review_passes_reach_the_tool_bodies(tmp_path):
    policy, events, state = await play(tmp_path, [[["work", {"bad": True}], ["work", {}]], [["exit", {}]]])
    assert policy.ran == ["work", "exit"]   # one `work` of the first response, then the exit
    refused = next(m for m in state["messages"] if isinstance(m, ToolMessage) and m.status == "error")
    assert (refused.content, refused.tool_call_id, refused.name) == ("refused: no", "n-1-0", "work")
    allowed = next(m for m in state["messages"] if isinstance(m, ToolMessage) and m.tool_call_id == "n-1-1")
    assert (allowed.content, allowed.status) == ("worked", "success")


async def test_no_model_call_after_exit(tmp_path):
    policy, events, state = await play(tmp_path, [[["exit", {}]], "never asked for"])
    assert len(ASKED) == 1   # the script's next step was never asked for
    assert state["node"]["ending"]["outcome"] == "done"


async def test_the_text_of_a_response_with_calls_is_in_the_next_request_once(tmp_path):
    from agent_core.contracts.events import ModelRequested

    steps = [{"text": "thinking aloud", "calls": [["work", {}]]}, [["exit", {}]]]
    policy, events, state = await play(tmp_path, steps)
    requests = [e for e in events.seen if isinstance(e, ModelRequested)]
    conversation = next(p for p in requests[1].parts if p.kind == "conversation").messages
    assert [(m.kind, m.text) for m in conversation if m.kind == "agent"] == [("agent", "thinking aloud")]
    assert [m.kind for m in conversation] == ["user", "agent", "call"]


async def test_each_response_is_given_to_the_policy_once_before_its_calls_run(tmp_path):   # SS-7
    policy, events, state = await play(tmp_path, [[["work", {}], ["work", {"x": 1}]], "done"])
    assert policy.seen == [("responded", 2), ("call", "work"), ("call", "work"), ("responded", 0)]
