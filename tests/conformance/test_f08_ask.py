"""F8 ask a person: `ask` puts a question to the person and waits; with nobody there the node ends `needs_input`."""

import asyncio
import time

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from agent_core.contracts.events import ToolReturned
INTERRUPT = "__interrupt__"   # the channel LangGraph writes a paused run's interrupts to

ASK = [["ask", {"question": "Which colour?"}]]
EXIT = [["exit", {"outcome": "done", "outputs": {"colour": "red"}}]]


class Person:
    def __init__(self, answer):
        self.answer, self.asked, self.told = answer, [], []

    async def tell(self, text):
        self.told.append(text)

    async def ask(self, question):
        self.asked.append((f"{question.node}#{question.number}", question.text))
        return self.answer


@pytest.mark.feature("F8")
async def test_the_persons_answer_is_the_result_of_the_call(harness):
    person = Person("green")
    h = harness({"ask": [ASK, EXIT]}, person=person)
    outcome = await h.nodes.run("ask")
    assert person.asked == [("ask#1", "Which colour?")]
    assert [e.text for e in h.events.record() if isinstance(e, ToolReturned)][0] == "green"
    assert outcome.exit == "done"


@pytest.mark.feature("F8")
async def test_with_nobody_there_the_node_ends_needing_input_and_says_what(harness):   # JOB-6
    h = harness({"ask": [ASK, EXIT]})
    outcome = await h.nodes.run("ask")
    assert (outcome.exit, outcome.reason, outcome.detail) == ("failed", "needs_input", {"question": "Which colour?"})
    assert outcome.notes[0].model_calls == 1   # the run ended at the question: no further model call
    [(_, text, error)] = [(e.call.name, e.text, e.error) for e in h.events.record() if isinstance(e, ToolReturned)]
    assert (text, error) == ("not answered: nobody is there", True)


@pytest.mark.feature("F8")
async def test_ask_must_be_the_only_call_of_its_response_and_the_person_is_not_asked(harness):   # VERB-6
    person = Person("green")
    h = harness({"ask": [[*ASK, ["state_get", {"key": "x"}]], EXIT]}, person=person)
    await h.nodes.run("ask")
    assert person.asked == []


class Slow(Person):
    async def ask(self, question):
        await asyncio.sleep(2)
        return await super().ask(question)


@pytest.mark.feature("F8")
async def test_ask_waits_for_the_person_inside_the_call(harness, backend_name, monkeypatch):
    saver = InMemorySaver()
    if backend_name == "langgraph":   # look at the graph's own history afterwards
        from agent_core.backends.langgraph import backend as module

        real = module.create_agent
        monkeypatch.setattr(module, "create_agent", lambda *a, **k: real(*a, **{**k, "checkpointer": saver}))
    person = Slow("green")
    h = harness({"ask": [ASK, EXIT]}, person=person)
    started = time.monotonic()
    outcome = await h.nodes.run("ask")
    assert time.monotonic() - started >= 2   # the run waited for the person
    assert [e.text for e in h.events.record() if isinstance(e, ToolReturned)][:1] == ["green"]
    assert (outcome.exit, outcome.outputs) == ("done", {"colour": "red"})
    if backend_name == "langgraph":
        history = [t async for t in saver.alist(None)]
        assert history   # the checkpointer saw the run, so an empty search proves something
        assert not [w for t in history for w in t.pending_writes if w[1] == INTERRUPT]
