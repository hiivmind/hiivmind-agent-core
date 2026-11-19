"""The job criteria with a real model, through the facade on the model-test instance.

NODE-7 (a node asks only for inputs it was not given), NODE-14 (a precondition written in the procedure), JOB-6 (a
question with nobody there, and with a person), JOB-7b (outputs of the wrong shape are corrected once) and JOB-12 (a node
that stops without `exit`).
"""

import pytest

from agent_core.contracts.events import ToolReturned

pytestmark = pytest.mark.model


class Person:
    def __init__(self, answer):
        self.answer, self.asked, self.told = answer, [], []

    async def tell(self, text):
        self.told.append(text)

    async def ask(self, question, label=""):
        self.asked.append((label, question))
        return self.answer


def returned(h) -> list[tuple[str, str, bool]]:
    return [(e.call.name, e.text, e.error) for e in h.events.record() if isinstance(e, ToolReturned)]


async def test_a_question_with_nobody_there_ends_the_node_as_needs_input(harness):   # JOB-6
    h = harness()
    outcome = await h.nodes.run("ask")
    assert (outcome.exit, outcome.reason) == ("failed", "needs_input")
    assert outcome.detail == {"question": "Which colour?"}
    assert [name for name, _, _ in returned(h)] == ["ask"]


async def test_a_question_put_to_a_person_is_answered_and_the_node_goes_on(harness):   # JOB-6
    person = Person("green")
    h = harness(person=person)
    outcome = await h.nodes.run("ask")
    assert [question for _, question in person.asked] == ["Which colour?"]
    assert (outcome.exit, outcome.outputs) == ("done", {"colour": "green"})


async def test_a_node_asks_only_for_an_input_it_was_not_given(harness):   # NODE-7
    given = Person("never used")
    h = harness(person=given)
    outcome = await h.nodes.run("choose", {"colour": "blue"})
    assert given.asked == []
    assert (outcome.exit, outcome.outputs) == ("done", {"colour": "blue"})

    person = Person("green")
    h = harness(person=person)
    outcome = await h.nodes.run("choose")
    assert [question for _, question in person.asked] == ["Which colour?"]
    assert (outcome.exit, outcome.outputs) == ("done", {"colour": "green"})
    assert "state_set" in [name for name, _, _ in returned(h)]   # the answer was recorded against the input


async def test_a_precondition_written_in_the_procedure_that_is_unmet_fails_the_node(harness):   # NODE-14
    h = harness()
    outcome = await h.nodes.run("guarded", {"name": "zeta"})
    assert outcome.exit == "failed"
    assert isinstance(outcome.outputs.get("reason"), str) and outcome.outputs["reason"]
    assert "lookup_revision" not in [name for name, _, _ in returned(h)]   # no later step ran


async def test_a_precondition_that_is_met_lets_the_node_go_on(harness):   # NODE-14
    h = harness()
    outcome = await h.nodes.run("guarded", {"name": "alpha"})
    assert (outcome.exit, outcome.outputs) == ("done", {"revision": "r1"})


async def test_outputs_of_the_wrong_shape_are_returned_to_the_model_once(harness):   # JOB-7b
    h = harness()
    outcome = await h.nodes.run("badshape")
    results = returned(h)
    assert results[0][0] == "exit" and results[0][2], results   # the first exit was refused
    assert results[0][1].startswith("the outputs do not match the node's output schema: [")
    assert (outcome.exit, outcome.outputs.get("total") if outcome.exit == "done" else outcome.reason) in (
        ("done", 3), ("failed", "invalid_output")
    )
    assert len(results) == 2   # one correction, and then the end


async def test_a_node_that_stops_without_exit_is_no_exit(harness):   # JOB-12
    h = harness()
    outcome = await h.nodes.run("silent")
    assert (outcome.exit, outcome.reason) == ("failed", "no_exit")
    assert "FINISHED" in outcome.detail.get("said", "")
