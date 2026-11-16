"""Walking a named sequence (design §4.2), with the `none` journal and node runs the test scripts."""

from pathlib import Path

import pytest

from agent_core.core.checks import unmet_check
from agent_core.core.instance import load_instance
from agent_core.core.registry import provider
from agent_core.core.sequences import SequenceRunner
from agent_core.resources.folder import FolderResources
from agent_core.tools.function import FunctionSource

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "sequences"
RESULTS = {
    "update-sources": {"outcome": "updated", "outputs": {"rescan_batches": ["b1", "b2", "b3"], "sources_updated": ["polars"]}},
    "scan": {"outcome": "done", "outputs": {"entries": ["e1"]}},
    "index": {"outcome": "done", "outputs": {"entries": ["e1", "e2"]}},
    "verify": {"outcome": "done", "outputs": {"drift": 0}},
    "publish": {"outcome": "published", "outputs": {"pr_url": "https://example.org/pr/1"}},
    "status": {"outcome": "stale", "outputs": {"refresh_needed": True}},
    "migrate": {"outcome": "done", "outputs": {"entry_count": 3}},
    "graph": {"outcome": "done", "outputs": {"result": "ok"}},
}


class Nodes:
    """A `run_node` that gives each node its result from `results`, and keeps (node, inputs) of each run."""

    def __init__(self, **results):
        self.results = {**RESULTS, **{k.replace("_", "-"): v for k, v in results.items()}}
        self.runs: list[tuple[str, dict]] = []

    async def __call__(self, node: str, inputs: dict) -> dict:
        self.runs.append((node, inputs))
        return self.results[node]

    @property
    def names(self) -> list[str]:
        return [node for node, _ in self.runs]


@pytest.fixture
def instance():
    return load_instance(FIXTURE / "instance.yaml", FolderResources(FIXTURE))


@pytest.fixture
def walk(instance, tmp_path, monkeypatch):
    """`await walk(name, facts, nodes=Nodes(), check=None)` walks the sequence with the `none` journal."""
    monkeypatch.setenv("AGENT_CORE_RUN_DIR", str(tmp_path))
    source = FunctionSource(instance.functions, None, FIXTURE)
    tools = {name: (source, None) for name in instance.functions}

    async def real_check(checks, facts, owner):
        return await unmet_check(checks, facts, owner=owner, tools=tools, functions=set(instance.functions), fill=str)

    async def call_tool(tool, args):
        return await source.call(tool, args, {})

    async def run(name, facts=None, *, nodes=None, check=None):
        runner = SequenceRunner(instance, nodes or Nodes(), call_tool, check or real_check)
        return await provider("journal", "none")().start("run-1", runner.walk, name, dict(facts or {}))

    return run


def names(result):
    return [entry["name"] for entry in result["trail"]]


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
    assert nodes.runs == [("migrate", {}), ("index", {"scans": [["e1"]]}), ("verify", {"entries": ["e1", "e2"]})]
    assert result["facts"] == {"scan_results": [["e1"]], "entry_count": 3, "entries": ["e1", "e2"], "drift": 0}


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
    assert nodes.runs == [("graph", {"action": "show"}), ("graph", {"action": "validate"})]
