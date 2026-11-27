"""F16 orchestration: a sequence walks its transitions, and a declared fragment is one step that runs its nodes.

The fragment's contract is architecture §4.3's, written once here for every backend: its inputs are found by name, its
outputs are the declared ones, a fan-out's results come back in item order with its failures beside them, and a stop
ends it.
"""

import asyncio

import pytest

from agent_core.contracts.events import ModelRequested, NodeEnded, NodeStarted, ToolReturned

LOOKUP = [[["lookup_revision", {}]], [["exit", {"outcome": "done", "outputs": {}}]]]
COUNT = [[["exit", {"outcome": "done", "outputs": {"total": 7}}]]]
SCRIPTS = {"lookup": LOOKUP, "count": COUNT}


@pytest.mark.feature("F16")
async def test_a_sequence_walks_from_node_to_node_on_each_outcome(harness):
    result = await harness({"lookup": LOOKUP, "count": COUNT}).sequences.run("lookup_then_count", {"name": "beta"})
    assert (result.end, result.facts["revision"], result.facts["total"]) == ("done", "r2", 7)
    assert [(s["name"], s["outcome"]) for s in result.steps] == [("lookup", "done"), ("count", "done")]


@pytest.mark.feature("F16")
async def test_a_transitions_mapping_gives_a_node_the_fact_it_names(harness):   # SEQ-5
    h = harness({"lookup": LOOKUP, "count": [[["state_get", {"key": "revisions"}]], *COUNT]})
    await h.sequences.run("lookup_then_count", {"name": "beta"})
    assert [e.text for e in h.events.record() if isinstance(e, ToolReturned) and e.call.name == "state_get"] == ['"r2"']


@pytest.mark.feature("F16")
async def test_a_sequence_whose_node_fails_ends_failed(harness):
    result = await harness(SCRIPTS).sequences.run("lookup_then_count", {"name": "nope"})
    assert (result.end, [(s["name"], s["outcome"]) for s in result.steps]) == ("failed", [("lookup", "failed")])


@pytest.mark.feature("F16")
async def test_the_fragment_contract(harness):
    h = harness(SCRIPTS)
    result = await h.sequences.run("pairs", {"names": ["alpha", "beta", "gamma"], "colour": "red"})
    assert result.end == "done"
    assert result.facts["revisions"] == [{"revision": "r1"}, {"revision": "r2"}, {"revision": "r3"}]   # in item order (FAN-3)
    assert (result.facts["revisions_failures"], result.facts["total"]) == ([], 7)
    [step] = result.steps   # at macro level the fragment is one step with its own steps listed
    assert (step["name"], step["outcome"]) == ("pair", "done")
    assert [s["name"] for s in step["steps"]] == ["lookup[1]", "lookup[2]", "lookup[3]", "lookup", "count"]


@pytest.mark.feature("F16")
async def test_a_fragments_nodes_get_only_the_inputs_they_declare_by_name(harness):   # SEQ-5, ORC-4
    h = harness({"lookup": LOOKUP, "count": [[["state_get", {"key": "revisions"}], ["state_get", {"key": "colour"}]], *COUNT]})
    await h.sequences.run("pairs", {"names": ["alpha"], "colour": "red"})
    assert [e.text for e in h.events.record() if isinstance(e, ToolReturned) and e.call.name == "state_get"] == [
        '[{"revision": "r1"}]', "not set",
    ]


@pytest.mark.feature("F16")
async def test_an_item_that_fails_is_listed_beside_the_results_and_the_fragment_goes_on(harness):   # FAN-2, FAN-4
    result = await harness(SCRIPTS).sequences.run("pairs", {"names": ["alpha", "nope", "gamma"]})
    assert result.end == "done"
    assert result.facts["revisions"] == [{"revision": "r1"}, {"revision": "r3"}]
    assert result.facts["revisions_failures"] == [{"item": "nope", "outcome": "failed", "reason": "precondition_unmet"}]


@pytest.mark.feature("F16")
async def test_a_fan_out_in_which_every_item_fails_ends_the_fragment_failed(harness):   # FAN-4
    result = await harness(SCRIPTS).sequences.run("pairs", {"names": ["nope", "never"]})
    assert result.end == "failed"
    assert result.facts["revisions"] == []
    assert [f["item"] for f in result.facts["revisions_failures"]] == ["nope", "never"]
    assert "total" not in result.facts   # `count` did not run


@pytest.mark.feature("F16")
async def test_a_fan_out_over_no_items_is_done(harness):   # FAN-4
    result = await harness(SCRIPTS).sequences.run("pairs", {"names": []})
    assert (result.end, result.facts["revisions"], result.facts["total"]) == ("done", [], 7)


@pytest.mark.feature("F16")
async def test_a_node_that_stops_ends_the_fragment_and_the_sequence_stopped(harness):   # SEQ-7
    h = harness({"lookup": [[["exit", {"outcome": "stopped", "outputs": {}}]]], "count": COUNT})
    result = await h.sequences.run("pairs", {"names": ["alpha", "beta"]})
    assert result.end == "stopped" and "total" not in result.facts
    assert "count" not in [e.node for e in h.events.record() if isinstance(e, NodeStarted)]


@pytest.mark.feature("F16")
async def test_a_nodes_own_preconditions_apply_inside_a_fragment(harness):   # NODE-13
    h = harness(SCRIPTS)
    await h.sequences.run("pairs", {"names": ["nope"]})
    assert [e.node for e in h.events.record() if isinstance(e, NodeStarted)] == []   # `nope` never started a model run


@pytest.mark.feature("F16")
async def test_a_fragment_outputs_are_the_declared_ones_and_the_nodes_other_outputs_stay_inside(harness):   # SEQ-6
    result = await harness(SCRIPTS).sequences.run("singles", {"name": "alpha"})
    assert result.end == "done"
    assert result.facts == {"name": "alpha", "total": 7}   # `lookup` produced `revision` and it is not the fragment's output
    assert result.summary == {"total": 7}   # what the backend returned, before the macro walk filters the facts


@pytest.mark.feature("F16")
async def test_a_transition_inside_a_fragment_maps_a_fact_to_the_input_a_node_declares(harness):   # SEQ-5
    h = harness({"lookup": LOOKUP, "count": [[["state_get", {"key": "revisions"}]], *COUNT]})
    await h.sequences.run("singles", {"name": "beta"})
    assert [e.text for e in h.events.record() if isinstance(e, ToolReturned) and e.call.name == "state_get"] == ['"r2"']


@pytest.mark.feature("F16")
async def test_a_node_that_exits_skipped_inside_a_fragment_follows_its_row(harness):   # SEQ-8
    h = harness({
        "lookup": [[["exit", {"outcome": "skipped", "outputs": {}}]]],
        "count": [[["state_get", {"key": "revisions"}]], *COUNT],
    })
    result = await h.sequences.run("singles", {"name": "alpha"})
    assert result.end == "done"
    [step] = result.steps
    assert step["steps"] == [{"name": "lookup", "outcome": "skipped"}, {"name": "count", "outcome": "done"}]
    assert [e.text for e in h.events.record() if isinstance(e, ToolReturned) and e.call.name == "state_get"] == ["not set"]   # nothing was found to map


@pytest.mark.feature("F16")
async def test_a_failure_inside_a_fragment_keeps_its_reason_and_message_in_the_record(harness):   # JOB-9a, JOB-13
    result = await harness(SCRIPTS).sequences.run("singles", {"name": "nope"})
    assert result.end == "failed"
    [inner] = [f for f in result.record.failures if f["node"] == "single/lookup"]
    assert inner["reason"] == "precondition_unmet" and inner["message"] == "The register does not hold nope."
    assert [s["name"] for s in result.steps[0]["steps"]] == ["lookup"]
    assert result.steps[0]["steps"][0]["reason"] == "precondition_unmet"


@pytest.mark.feature("F16")
async def test_a_fragment_step_with_no_transition_fails_no_transition(harness):   # SEQ-10, E6
    result = await harness({
        "lookup": LOOKUP, "count": [[["exit", {"outcome": "skipped", "outputs": {}}]]],   # `single` has no row for it
    }).sequences.run("singles", {"name": "alpha"})
    assert result.end == "failed"
    [failure] = [f for f in result.record.failures if f["node"] == "single"]
    assert failure == {"node": "single", "outcome": "failed", "reason": "no_transition",
                       "message": "`count` exited `skipped` and the sequence has no transition for it", "outputs": {}}


@pytest.mark.feature("F16")
async def test_a_nodes_own_failure_reason_stays_in_its_outputs_when_the_fragment_goes_on(harness):   # JOB-9a, JOB-13
    own = {"reason": "not found", "revision": "none"}
    result = await harness({
        "lookup": [[["exit", {"outcome": "failed", "outputs": own}]]], "count": COUNT,
    }).sequences.run("tolerates", {"name": "alpha"})
    assert result.end == "done"   # the fragment recovered
    [inner] = [f for f in result.record.failures if f["node"] == "tolerant/lookup"]
    assert inner == {"node": "tolerant/lookup", "outcome": "failed", "outputs": own}   # no harness `reason`
    assert result.steps[0]["steps"][0] == {"name": "lookup", "outcome": "failed", "outputs": own}


@pytest.mark.feature("F16")
async def test_a_fan_outs_concurrency_limit_is_honoured_inside_a_fragment(harness):   # FAN-1
    slow = [[["shell__run", {"command": "sleep 0.3"}]], COUNT[0]]
    h = harness({"count": slow})
    result = await h.sequences.run("tallies", {"names": ["a", "b", "c", "d", "e"]})
    assert result.end == "done" and len(result.facts["totals"]) == 5
    running, peak = 0, 0
    for event in h.events.record():
        if isinstance(event, NodeStarted | NodeEnded):
            running += 1 if isinstance(event, NodeStarted) else -1
            peak = max(peak, running)
    assert peak == 2   # `max_concurrency: 2` of the fragment's fan-out: two at once, never more


@pytest.mark.feature("F16")
async def test_a_list_computed_by_a_tool_is_a_step_of_the_fragment(harness):   # FAN-5
    h = harness(SCRIPTS)
    result = await h.sequences.run("rosters", {})
    assert result.end == "done"
    assert result.facts["revisions"] == [{"revision": "r1"}, {"revision": "r2"}]
    [step] = result.steps
    assert [s["name"] for s in step["steps"]] == ["lookup[list]", "lookup[1]", "lookup[2]", "lookup"]


@pytest.mark.feature("F16", "F12")   # a refusal needs a model: skipped where F12 is not built
async def test_an_item_the_provider_refused_is_run_once_more_from_a_fresh_context_inside_a_fragment(harness, monkeypatch):   # RTY-2, RTY-3
    monkeypatch.setenv("AGENT_CORE_LANGGRAPH_MAX_RETRIES", "0")   # the refusal reaches the fan-out at once
    monkeypatch.setattr("agent_core.backends.langgraph.fragments.RETRY_PAUSE", 0)
    refused_once = [[["lookup_revision", {}]], {"raise": "passes", "once": True}, [["exit", {"outcome": "done", "outputs": {}}]]]
    h = harness({"lookup": refused_once, "count": COUNT})
    result = await h.sequences.run("pairs", {"names": ["alpha"]})
    assert (result.end, result.facts["revisions"], result.facts["revisions_failures"]) == ("done", [{"revision": "r1"}], [])
    sent = [e for e in h.events.record() if isinstance(e, ModelRequested)]
    lengths = [len(next(p for p in e.parts if p.kind == "conversation").messages) for e in sent[:4]]
    assert lengths == [1, 2, 1, 2]   # the second run starts again from the opening, and does not carry the first run's call


@pytest.mark.feature("F16")
async def test_each_run_of_a_fan_out_starts_with_a_thread_of_its_own(harness, monkeypatch):   # SS-14, design §3.2
    from agent_core.core.facade import _Run

    started, real = [], _Run.start

    async def start(self, node, inputs, thread):
        started.append((node, thread))
        return await real(self, node, inputs, thread)

    monkeypatch.setattr(_Run, "start", start)
    await harness(SCRIPTS).sequences.run("pairs", {"names": ["alpha", "beta"]})
    threads = [thread for node, thread in started if node == "lookup"]
    assert len(threads) == 2 and len(set(threads)) == 2 and all(threads)


@pytest.mark.feature("F16")
async def test_a_run_that_raises_keeps_the_outputs_its_finished_steps_returned(harness):   # SS-10, plan review A5
    result = await harness({"lookup": LOOKUP}).sequences.run("lookup_then_count", {"name": "alpha"})   # `count` has no script: it raises
    assert result.end == "failed"
    assert result.outputs == {"revision": "r1"}


class _GoneAtFirst:
    """A person who has gone at the first question (after the other item is waiting for its turn), and holds a second
    open: it is never answered, and it notes whether it was cancelled."""

    def __init__(self):
        self.asked, self.cancelled = 0, False

    async def tell(self, text):
        pass

    async def hear(self):
        return None

    async def ask(self, question):
        from agent_core.contracts.errors import SessionWaits

        self.asked += 1
        if self.asked == 1:
            await asyncio.sleep(0.3)   # the other item reaches its own question meanwhile, and waits its turn
            raise SessionWaits()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


@pytest.mark.feature("F16")
async def test_a_base_exception_in_one_fan_out_item_stops_the_others_and_is_raised_as_it_was(harness):   # SS-6, SS-15
    from agent_core.contracts.errors import SessionWaits

    person = _GoneAtFirst()
    h = harness({"lookup": [[["ask", {"question": "Which?"}]], LOOKUP[1]], "count": COUNT}, person=person)
    with pytest.raises(SessionWaits):
        await h.sequences.run("pairs", {"names": ["alpha", "beta"]})
    seen = len(h.events.record())
    await asyncio.sleep(0.3)
    assert len(h.events.record()) == seen
    assert person.asked == 1 or person.cancelled   # the other item was stopped before it was asked, or while it was
