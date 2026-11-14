import dataclasses

import pytest

from agent_core.contracts import (
    Brief, EndRun, HandoverRequest, Message, ModelResponse, Result, RunEnd, ToolCall, ToolError, ToolServerError,
    ToolSpec,
)


def test_values_are_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        Brief("i", (), (), "o").opening = "x"


def test_a_brief_is_hashable_only_through_its_identity_and_holds_tuples():
    b = Brief("i", (ToolSpec("t", "d", {}),), (Message("user", "hello"),), "Run the node.")
    assert isinstance(b.tools, tuple) and isinstance(b.handover, tuple)


def test_everything_is_exported_from_the_package():
    import agent_core.contracts as c
    for name in ["ToolSpec", "Message", "Brief", "ToolCall", "ModelResponse", "Result", "EndRun", "RunEnd", "ToolError",
                 "ToolServerError", "NodeDriver", "NodeController", "ContextStrategy", "HandoverRequest", "ToolSource",
                 "ResourceSource", "State", "StateStore", "Person"]:
        assert hasattr(c, name), name


def test_defaults():
    m = Message("call")
    assert (m.text, m.call_id, m.name, m.result) == ("", "", "", "") and m.args == {}
    assert Message("call").args is not Message("call").args
    assert Result("x").error is False
    assert EndRun() == EndRun()


def test_values_carry_their_fields():
    r = ModelResponse("t", (ToolCall("1", "n", {"a": 1}),), None, 3, 4)
    assert r.calls[0].args == {"a": 1} and r.sent is None and (r.cache_read, r.cache_written) == (3, 4)
    assert RunEnd(True, "bye") == RunEnd(by_controller=True, said="bye")


def test_handover_request_is_frozen():
    async def summarise(a: str, b: str) -> str:
        return a + b
    h = HandoverRequest((), {}, "n", {}, summarise)
    with pytest.raises(dataclasses.FrozenInstanceError):
        h.node = "x"


def test_errors_are_distinct_exceptions():
    assert issubclass(ToolError, Exception) and issubclass(ToolServerError, Exception)
    assert not issubclass(ToolError, ToolServerError) and not issubclass(ToolServerError, ToolError)


def test_person_ask_takes_a_label():
    import inspect
    from agent_core.contracts import Person
    p = inspect.signature(Person.ask).parameters
    assert list(p) == ["self", "question", "label"] and p["label"].default == ""
