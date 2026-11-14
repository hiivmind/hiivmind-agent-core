"""Obligations of a backend, written against `NodeDriver` and run on each backend that has a model.

Each test names the obligation it checks. Each calls the model, so they carry the marker `model`.
"""

import time

import pytest

from agent_core.contracts import Brief, Message

pytestmark = pytest.mark.model


def one_lookup(instructions) -> str:
    return instructions(
        "1. Call `lookup` with the name `alpha`, alone in its response.\n"
        "2. Then call `exit` with the summary `done`, alone in its response."
    )


async def test_the_wire_carries_the_brief_and_nothing_else(driver, wire, controller, instructions, toy_tools):  # KIT-2, KIT-3, KIT-4
    brief = Brief(one_lookup(instructions), toy_tools, (), "Begin the procedure.")
    end = await driver.drive(brief, controller)

    first = wire.requests[0]
    assert wire.system_text(first) == brief.instructions
    assert wire.tools(first) == [(t.name, t.description, t.schema) for t in brief.tools]
    messages = wire.messages(first)
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert wire.text_of(messages[0]["content"]) == brief.opening
    assert end.by_controller


async def test_instructions_and_tools_do_not_change_during_a_run(driver, wire, controller, instructions, toy_tools):  # SCOPE-2
    procedure = (
        "Look up each of these sources, in this order, making one call in each response and waiting for its result "
        "before the next: alpha, beta, gamma, delta, epsilon.\n"
        "When the fifth result is in, call `exit` with the summary `done`, alone in its response."
    )
    brief = Brief(instructions(procedure), toy_tools, (), "Begin the procedure.")
    await driver.drive(brief, controller)

    assert len(controller.handled) == 6
    assert len(wire.requests) == len(controller.responses) == 6
    for body in wire.requests:
        assert wire.system_text(body) == brief.instructions
        assert wire.tools(body) == [(t.name, t.description, t.schema) for t in brief.tools]
    for before, after in zip(wire.requests, wire.requests[1:]):
        kept = wire.messages(before)
        assert wire.messages(after)[: len(kept)] == kept
        assert len(wire.messages(after)) > len(kept)


async def test_most_of_each_request_is_read_from_cache(driver, wire, controller, instructions, toy_tools):  # KIT-7
    procedure = (
        "Look up each of these sources, in this order, making one call in each response and waiting for its result "
        "before the next: alpha, beta, gamma.\n"
        "When the third result is in, call `exit` with the summary `done`, alone in its response."
    )
    brief = Brief(instructions(procedure, notes=160), toy_tools, (), "Begin the procedure.")
    await driver.drive(brief, controller)

    assert len(controller.responses) >= 3
    assert controller.responses[0].sent >= 3000
    for response in controller.responses[1:]:
        assert response.sent
        assert (response.cache_read or 0) / response.sent >= 0.8


async def test_a_response_is_reported_before_its_calls(driver, wire, controller, instructions, toy_tools):  # KIT-5
    procedure = (
        "1. In one response, make two calls together: `lookup` with the name `alpha` and `lookup` with the name `beta`.\n"
        "2. When both results are in, call `exit` with the summary `done`, alone in its response."
    )
    brief = Brief(instructions(procedure), toy_tools, (), "Begin the procedure.")
    await driver.drive(brief, controller)

    pair = next(i for i, (kind, item) in enumerate(controller.events) if kind == "responded" and len(item.calls) == 2)
    response = controller.events[pair][1]
    handled = [i for i, (kind, item) in enumerate(controller.events) if kind == "handle" and item in response.calls]
    assert len(handled) == 2
    assert all(i > pair for i in handled)
    assert {call.id for call in response.calls} == {controller.events[i][1].id for i in handled}
    assert all(call.id for call in response.calls)


async def test_no_model_call_after_the_run_is_ended(driver, wire, controller, instructions, toy_tools):  # KIT-6
    end = await driver.drive(Brief(one_lookup(instructions), toy_tools, (), "Begin the procedure."), controller)

    assert end.by_controller
    assert controller.handled[-1].name == "exit"
    assert len(wire.requests) == len(controller.responses)
    assert len(controller.responses) == 2  # the lookup, then the exit
    assert controller.events[-1][0] == "handle" and controller.events[-1][1].name == "exit"  # nothing is reported after the end


async def test_the_model_stopping_is_put_to_the_controller(driver, wire, controller, instructions, toy_tools):  # KIT-10
    procedure = (
        "Say exactly `READY?` and make no call. When the user answers, call `exit` with the summary `done`, "
        "alone in its response."
    )
    brief = Brief(instructions(procedure), toy_tools, (), "Begin the procedure.")

    controller.replies = ["Go on: make the call to exit now."]
    end = await driver.drive(brief, controller)
    assert len(controller.said) == 1 and "READY?" in controller.said[0]
    second = wire.requests[1]
    assert [m["role"] for m in wire.messages(second)] == ["user", "assistant", "user"]
    assert wire.text_of(wire.messages(second)[2]["content"]) == "Go on: make the call to exit now."
    assert wire.messages(second)[:1] == wire.messages(wire.requests[0])
    assert end.by_controller and controller.handled[-1].name == "exit"

    sent = len(wire.requests)
    quiet = type(controller)()
    end = await driver.drive(brief, quiet)
    assert len(quiet.said) == 1 and "READY?" in quiet.said[0]
    assert not end.by_controller
    assert "READY?" in end.said
    assert len(wire.requests) == sent + 1


async def test_a_call_held_for_twenty_seconds_is_not_cut_off(driver, wire, controller, instructions, toy_tools):  # PAUSE-1
    controller.hold = 20
    started = time.monotonic()
    end = await driver.drive(Brief(one_lookup(instructions), toy_tools, (), "Begin the procedure."), controller)

    assert time.monotonic() - started >= 20
    assert end.by_controller
    results = [
        block
        for message in wire.messages(wire.requests[1])
        if isinstance(message["content"], list)
        for block in message["content"]
        if block.get("type") == "tool_result"
    ]
    assert len(results) == 1
    assert "41" in str(results[0]["content"])
    assert not results[0].get("is_error")


async def test_a_second_run_inside_a_call(driver, wire, controller, instructions, toy_tools, quiet):  # KIT-1
    inner = Brief("Reply with the single word PONG and nothing else.", (), (), "ping")
    ends = []

    async def inside():
        ends.append(await driver.drive(inner, quiet))

    controller.inside = inside
    end = await driver.drive(Brief(one_lookup(instructions), toy_tools, (), "Begin the procedure."), controller)

    assert len(ends) == 1
    assert not ends[0].by_controller
    assert "PONG" in ends[0].said
    assert end.by_controller
    assert [call.name for call in controller.handled] == ["lookup", "exit"]


async def test_a_handover_with_calls_reaches_the_provider_as_calls(driver, wire, controller, instructions, toy_tools):  # KIT-11
    procedure = (
        "The user asked for the revisions of `alpha` and `beta`. Each was already looked up, in the conversation so far. "
        "Do not look anything up again. Call `exit` with the summary `alpha=41 beta=7`, alone in its response."
    )
    handover = (
        Message("user", "Look up alpha and beta."),
        Message("call", call_id="toolu_handover_1", name="lookup", args={"name": "alpha"}, result="revision 41"),
        Message("call", call_id="toolu_handover_2", name="lookup", args={"name": "beta"}, result="revision 7"),
    )
    end = await driver.drive(Brief(instructions(procedure), toy_tools, handover, ""), controller)

    first = wire.messages(wire.requests[0])
    assert [m["role"] for m in first] == ["user", "assistant", "user", "assistant", "user"]
    uses = [b for m in first if m["role"] == "assistant" for b in m["content"] if b.get("type") == "tool_use"]
    assert [(u["id"], u["name"], u["input"]) for u in uses] == [
        ("toolu_handover_1", "lookup", {"name": "alpha"}),
        ("toolu_handover_2", "lookup", {"name": "beta"}),
    ]
    results = [
        b for m in first if m["role"] == "user" and isinstance(m["content"], list) for b in m["content"] if b.get("type") == "tool_result"
    ]
    assert [r["tool_use_id"] for r in results] == ["toolu_handover_1", "toolu_handover_2"]
    assert end.by_controller
    assert [call.name for call in controller.handled] == ["exit"]


async def test_a_brief_with_no_tools_gives_a_plain_reply(driver, wire, quiet):  # CTX-2
    text = "The user asked for a refresh of polars. The node `refresh` ran and finished done: 3 entries changed."
    brief = Brief("Summarise the text you are given in one sentence. Reply with the sentence only.", (), (), text)
    end = await driver.drive(brief, quiet)

    assert end.said.strip()
    assert not end.by_controller
    assert not wire.requests[0].get("tools")


async def test_cache_counts_are_numbers_or_none(driver, wire, controller, instructions, toy_tools):  # KIT-5, SCOPE-7
    procedure = "Call `exit` with the summary `done`, alone in its response."
    await driver.drive(Brief(instructions(procedure, notes=160), toy_tools, (), "Begin the procedure."), controller)

    assert controller.responses
    for response in controller.responses:
        for count in (response.sent, response.cache_read, response.cache_written):
            assert count is None or (isinstance(count, int) and count >= 0)
    assert (controller.responses[0].cache_written or 0) > 0
