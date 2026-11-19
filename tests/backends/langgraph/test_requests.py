"""What each model request carries, reported as parts (Q4, CTX-6; SCOPE-2, TPL-4)."""

import json

from test_hook import FakePolicy, play

from agent_core.contracts.events import ModelRequested


async def test_each_request_names_its_parts(tmp_path):
    policy, events, _ = await play(tmp_path, [[["work", {}]], [["exit", {}]]])
    first, second = [e for e in events.seen if isinstance(e, ModelRequested)]
    assert [p.kind for p in first.parts] == ["instructions", "tools", "conversation"]
    instructions, tools, conversation = first.parts
    assert instructions.text == FakePolicy.instructions
    assert [(t["name"], t["description"], t["schema"]) for t in json.loads(tools.text)] == [
        (t.name, t.description, t.schema) for t in FakePolicy.tools
    ]
    assert [(m.kind, m.text) for m in conversation.messages] == [("user", "go")]
    assert [p.kind for p in second.parts] == ["instructions", "tools", "conversation"]
    assert second.parts[0] == instructions   # the instructions do not change after a call
    assert len(second.parts[2].messages) > len(conversation.messages)   # the conversation grows
