"""The intents of a unit (ORC-6) and the compiled fragment's second run of a refused item (RTY-2)."""

import json
import sys
from pathlib import Path

import pytest

CONFORMANCE = Path(__file__).resolve().parents[2] / "conformance"
sys.path.insert(0, str(CONFORMANCE))
import script_model  # noqa: E402, F401  (registers the `script` model provider)
from test_state import Events, StatePolicy  # noqa: E402

import agent_core  # noqa: E402
from agent_core.backends.langgraph.backend import LangGraphBackend  # noqa: E402
from agent_core.backends.langgraph.settings import LangGraphSettings  # noqa: E402
from agent_core.contracts.events import ModelRequested  # noqa: E402
from agent_core.contracts.unit import DeclaredTools, Unit  # noqa: E402
from agent_core.contracts.values import HarnessReason  # noqa: E402
from agent_core.contracts.topology import END, FragmentDef, Step  # noqa: E402
from agent_core.backends.langgraph.fragments import fragment_result  # noqa: E402

INSTANCE = CONFORMANCE / "instance" / "instance.yaml"
STEPS = [[["set", {"key": "mine", "value": "m"}]], [["exit", {}]]]


def unit_of(policy, *, intent, thread="t", run_dir=None):
    async def start(node, inputs):
        return policy

    async def call_tool(name, args):
        raise AssertionError

    return Unit("n", {}, intent, thread, start, DeclaredTools({}, frozenset(), None), Events(), None, call_tool, run_dir=run_dir)


@pytest.fixture
async def backend(tmp_path):
    (tmp_path / "n.json").write_text(json.dumps(STEPS))
    made = LangGraphBackend(LangGraphSettings(MODEL=f"script:{tmp_path}"))
    yield made
    await made.close()


async def test_a_continue_with_no_checkpoint_starts_the_unit(backend, tmp_path):   # ORC-6
    policy = StatePolicy()
    result = await backend.run_node(unit_of(policy, intent="continue", run_dir=tmp_path / "run"))
    assert result.exit == "done" and policy.ran == ["set", "exit"]   # the unit ran from its start
    assert (tmp_path / "run" / "checkpoints.sqlite").exists()


async def test_a_continue_with_a_checkpoint_resumes_it_and_runs_nothing_again(backend, tmp_path):   # ORC-6, §4.4a
    run = tmp_path / "run"
    first = StatePolicy()
    done = await backend.run_node(unit_of(first, intent="start", run_dir=run))
    again = StatePolicy()
    resumed = await backend.run_node(unit_of(again, intent="continue", run_dir=run))
    assert again.ran == []   # the checkpoint of the thread was finished: invoked with no input, nothing ran
    assert resumed == done


async def test_a_unit_with_no_run_directory_is_not_checkpointed(backend, tmp_path):
    result = await backend.run_node(unit_of(StatePolicy(), intent="start"))
    assert result.exit == "done" and not list(tmp_path.rglob("*.sqlite"))


async def test_the_second_run_of_a_refused_item_starts_from_a_fresh_context(tmp_path, monkeypatch):   # RTY-2
    monkeypatch.setenv("AGENT_CORE_LANGGRAPH_MAX_RETRIES", "0")
    monkeypatch.setattr("agent_core.backends.langgraph.fragments.RETRY_PAUSE", 0)
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "lookup.json").write_text(json.dumps([[["lookup_revision", {}]], {"raise": "passes"}]))
    (scripts / "count.json").write_text(json.dumps([[["exit", {"outcome": "done", "outputs": {"total": 7}}]]]))
    monkeypatch.setenv("AGENT_CORE_LANGGRAPH_MODEL", f"script:{scripts}")
    async with agent_core.open(INSTANCE, backend="langgraph", runs=tmp_path / "runs") as harness:
        result = await harness.sequences.run("pairs", {"names": ["alpha"]})
        sent = [e for e in harness.events.record() if isinstance(e, ModelRequested)]
    held = [[m.kind for m in next(p for p in e.parts if p.kind == "conversation").messages] for e in sent]
    assert held == [["user"], ["user", "call"], ["user"], ["user", "call"]]   # the second run's first request is the brief's messages only
    [failure] = result.facts["revisions_failures"]
    assert failure["reason"].endswith("(run twice)")   # refused again: the item fails, and is not run a third time


def test_no_transition_survives_the_checkpoint():   # Review Focus 3, CD-10
    """A fragment's state as the checkpointer writes and reads it back: the result's reason is still the enum."""
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    fragment = FragmentDef("f", (), (), ("done", "failed"), Step("count"), {"count": {"done": END}})
    state = {
        "facts": {}, "items": {}, "results": {}, "outcome": "skipped",
        "trail": [{"name": "count", "outcome": "failed", "reason": HarnessReason.NO_EXIT}],
        "ended": {"end": "failed", "message": "`count` exited `skipped` and the sequence has no transition for it"},
    }
    serde = JsonPlusSerializer()
    result = fragment_result(fragment, serde.loads_typed(serde.dumps_typed(state)))
    assert result.reason is HarnessReason.NO_TRANSITION
    assert result.detail == {"message": "`count` exited `skipped` and the sequence has no transition for it"}
    assert result.steps[0]["reason"] is HarnessReason.NO_EXIT
