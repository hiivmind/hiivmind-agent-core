"""Walking a named sequence or a fragment, with node runs the test scripts."""

from walking import Nodes, names

from agent_core.contracts.registry import REGISTERED
from agent_core.contracts.unit import UnitResult
from agent_core.contracts.walk import StepRef
from agent_core.helpers.walk import walk_fragment


async def test_a_sequence_follows_outcomes_to_the_end(walk):                               # SEQ-2
    result = await walk("chain", {"scan_results": [["e1"]]})
    assert result["end"] == "done"
    assert result["trail"] == [
        {"step": 1, "name": "migrate", "outcome": "done"},
        {"step": 2, "name": "index", "outcome": "done"},
        {"step": 3, "name": "verify", "outcome": "done"},
    ]
    assert result["summary"] == {"drift": 0}


async def test_inputs_are_filled_by_name_and_by_mapping(walk):                             # SEQ-5, SEQ-6
    nodes = Nodes()
    result = await walk("chain", {"scan_results": [["e1"]]}, nodes=nodes)
    assert nodes.inputs == [("migrate", {}), ("index", {"scans": [["e1"]]}), ("verify", {"entries": ["e1", "e2"]})]
    assert result["facts"] == {"scan_results": [["e1"]], "entry_count": 3, "entries": ["e1", "e2"], "drift": 0}


async def test_each_step_is_run_with_its_number_and_intent_start(walk):                    # ORC-4, ORC-6
    nodes = Nodes()
    await walk("chain", nodes=nodes)
    assert [(ref, intent) for _, _, ref, intent in nodes.runs] == [(StepRef(n), "start") for n in (1, 2, 3)]


async def test_checks_that_route(walk, monkeypatch):                                       # SEQ-9, criterion 1
    monkeypatch.setenv("SEQ_REFRESH_NEEDED", "0")
    nodes = Nodes()
    result = await walk("refresh", nodes=nodes)
    assert result["trail"] == [{"step": 1, "name": "checks", "outcome": "current"}]
    assert (result["end"], result["summary"], nodes.runs) == ("done", "Already current.", [])


async def test_a_check_without_an_outcome_ends_failed(walk, monkeypatch):
    monkeypatch.setenv("SEQ_READY", "0")
    result = await walk("refresh")
    assert (result["end"], result["summary"]) == ("failed", "The corpus is not ready.")
    assert names(result) == ["checks"]


def gate(check_row):
    """A sequence `gate` with one check, whose row is `check_row`, then `migrate`."""
    from agent_core.contracts.topology import END, Check, SequenceDef, Step

    return {"gate": SequenceDef("gate", "d", Step("migrate"), {}, (Check("ready", {}, "m"),),
                                {"check": check_row, "migrate": {"done": END}})}


async def test_a_check_that_gives_failed_ends_the_sequence_failed(walk):                   # §4.2 step 5, JOB-17
    async def broken(checks, facts, owner):
        return {"tool": "ready", "outcome": "failed", "message": "The corpus is broken."}, {}

    result = await walk("gate", check=broken, sequences=gate({"failed": "end"}))
    assert (result["end"], result["summary"]) == ("failed", "The corpus is broken.")


async def test_a_check_that_gives_stopped_ends_the_sequence(walk):                         # SEQ-7
    from agent_core.contracts.topology import Step

    async def halt(checks, facts, owner):
        return {"tool": "ready", "outcome": "stopped", "message": "Stopped by the owner."}, {}

    nodes = Nodes()
    result = await walk("gate", check=halt, nodes=nodes, sequences=gate({"stopped": Step("migrate")}))
    assert result["end"] == "stopped" and nodes.runs == []


async def test_met_checks_writes_become_facts(walk):                                       # SEQ-9, NODE-11
    async def stamping(checks, facts, owner):
        return None, {"stamp": "s"}

    nodes = Nodes(update_sources={"outcome": "current", "outputs": {}})
    result = await walk("refresh", check=stamping, nodes=nodes)
    assert result["facts"]["stamp"] == "s" and result["trail"][0] == {"step": 1, "name": "checks", "outcome": "met"}


async def test_stopped_ends_the_sequence(walk):                                            # SEQ-7
    nodes = Nodes(index={"outcome": "stopped", "outputs": {}})
    result = await walk("chain", nodes=nodes)
    assert nodes.names == ["migrate", "index"] and result["end"] == "stopped"


async def test_skipped_takes_its_transition(walk):                                         # SEQ-8
    nodes = Nodes(index={"outcome": "skipped", "outputs": {}})
    result = await walk("chain", nodes=nodes)
    assert nodes.names == ["migrate", "index", "verify"] and result["end"] == "done"


async def test_an_outcome_with_no_transition_ends_failed(walk):                            # SEQ-10
    nodes = Nodes(index={"outcome": "declined", "outputs": {}})
    result = await walk("chain", nodes=nodes)
    assert nodes.names == ["migrate", "index"] and result["end"] == "failed"
    assert "`index`" in result["summary"] and "`declined`" in result["summary"]


async def test_a_link_carries_the_facts(walk):                                             # SEQ-4
    seen = []

    async def current(checks, facts, owner):
        seen.append((owner, dict(facts)))
        return {"outcome": "current", "message": "Already current."}, {}

    result = await walk("status", check=current)
    assert seen == [("refresh", {"refresh_needed": True})]
    assert result["trail"] == [
        {"step": 1, "name": "status", "outcome": "stale"},
        {"step": 2, "name": "checks", "outcome": "current"},
    ]
    assert (result["end"], result["summary"]) == ("done", "Already current.")


async def test_a_link_makes_the_linked_sequences_checks(walk, monkeypatch):                 # Review Focus 4, NODE-13a
    monkeypatch.setenv("SEQ_INDEX_V2", "0")
    result = await walk("status")
    assert [(e["name"], e["outcome"]) for e in result["trail"]] == [("status", "stale"), ("checks", "v1"), ("migrate", "done")]
    assert result["end"] == "done"


async def test_fixed_inputs_fill_only_missing_facts(walk):                                 # §4.2 entering
    nodes = Nodes()
    await walk("graph", nodes=nodes)
    await walk("graph", {"action": "validate"}, nodes=nodes)
    assert nodes.inputs == [("graph", {"action": "show"}), ("graph", {"action": "validate"})]


async def test_a_fragment_is_a_step_and_its_outputs_merge_into_the_facts(walk):            # SEQ-6, ORC-4
    nodes = Nodes(tail=UnitResult("done", {"wrapped": "yes", "closed": "yes", "stray": 1},
                                  steps=({"name": "wrap", "outcome": "done"}, {"name": "close", "outcome": "done"})))
    from agent_core.contracts.topology import END, SequenceDef, Step

    rows = {"first": {"done": Step("tail"), "failed": END}, "tail": {"done": END}}   # the fixture has no row for `tail`
    result = await walk("with-tail", nodes=nodes, sequences={"with-tail": SequenceDef("with-tail", "d", Step("first"), {}, (), rows)})
    assert nodes.names == ["first", "tail"] and [ref for _, _, ref, _ in nodes.runs] == [StepRef(1), StepRef(2)]
    assert result["end"] == "done"
    assert result["facts"] == {"first_done": "yes", "wrapped": "yes", "closed": "yes"}   # undeclared `stray` is dropped
    assert result["trail"][1] == {"step": 2, "name": "tail", "outcome": "done",
                                  "steps": [{"name": "wrap", "outcome": "done"}, {"name": "close", "outcome": "done"}]}


async def test_a_fragments_exit_the_sequence_has_no_row_for_fails_at_the_macro_level(walk):   # SEQ-10
    nodes = Nodes(tail=UnitResult("failed", {}))
    result = await walk("with-tail", nodes=nodes)
    assert result["end"] == "failed" and "`tail`" in result["summary"] and "`failed`" in result["summary"]


async def test_a_fragment_runs_its_nodes_and_returns_its_exit_and_outputs(port):
    nodes = Nodes()
    p = port(nodes=nodes)
    r = await walk_fragment(p, p.topology.fragments["tail"], {"ignored": 1})
    assert nodes.runs == [("wrap", {}, StepRef(1), "start"), ("close", {}, StepRef(2), "start")]
    assert (r.exit, r.outputs, r.reason) == ("done", {"wrapped": "yes", "closed": "yes"}, None)
    assert r.steps == ({"name": "wrap", "outcome": "done"}, {"name": "close", "outcome": "done"})


async def test_a_fragments_exit_is_its_last_steps_outcome(port):                            # SEQ-10
    nodes = Nodes(close={"outcome": "failed", "outputs": {}})
    p = port(nodes=nodes)
    r = await walk_fragment(p, p.topology.fragments["tail"], {})
    assert r.exit == "failed" and r.steps[-1]["name"] == "close" and r.outputs == {"wrapped": "yes"}


async def test_an_outcome_the_fragment_has_no_row_for_ends_it_failed_naming_it(port):      # SEQ-10
    nodes = Nodes(wrap={"outcome": "declined", "outputs": {}})
    p = port(nodes=nodes)
    r = await walk_fragment(p, p.topology.fragments["tail"], {})
    assert nodes.names == ["wrap"] and r.exit == "failed"
    assert "`wrap`" in r.reason and "`declined`" in r.reason


async def test_a_stop_in_a_fragment_ends_it_stopped(port):                                  # SEQ-7
    nodes = Nodes(wrap={"outcome": "stopped", "outputs": {}})
    p = port(nodes=nodes)
    r = await walk_fragment(p, p.topology.fragments["tail"], {})
    assert nodes.names == ["wrap"] and r.exit == "stopped"


async def test_a_fragment_starts_from_its_declared_inputs_found_in_the_inputs(port):
    from agent_core.contracts.topology import END, FragmentDef, Step

    nodes = Nodes()
    fragment = FragmentDef("f", ("scans", "x", "absent"), ("entries", "x", "y"), ("done", "failed"), Step("index"),
                           {"index": {"done": END}})
    r = await walk_fragment(port(nodes=nodes), fragment, {"scans": [1], "x": 2, "y": 3})
    assert nodes.inputs == [("index", {"scans": [1]})]
    assert (r.exit, r.outputs) == ("done", {"entries": ["e1", "e2"], "x": 2})   # `y` was no declared input


def test_the_walk_registers_itself_with_its_two_functions():
    from agent_core.helpers import walk

    registered = REGISTERED["walk"]["topology"]
    assert (registered.walk_sequence, registered.walk_fragment) == (walk.walk_sequence, walk.walk_fragment)
