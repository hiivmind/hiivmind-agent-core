"""Example 2 of the architecture: a fragment killed inside a node resumes in that node, with its values (§4.4a).

A subprocess runs `agent-core job` on the conformance instance; the script of the fragment's second node ends the
process after a `state_set`. The resume is made in this process, so that the events of the resumed node can be read.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

CONFORMANCE = Path(__file__).resolve().parents[2] / "conformance"
sys.path.insert(0, str(CONFORMANCE))
import script_model  # noqa: E402, F401  (registers the `script` model provider)

import agent_core  # noqa: E402
from agent_core.contracts.events import NodeStarted, ToolReturned  # noqa: E402

INSTANCE = CONFORMANCE / "instance" / "instance.yaml"
RUN_ID = "singles-20261119T000000Z-abc123"
SCRIPTS = {
    "lookup": [[["lookup_revision", {}]], [["exit", {"outcome": "done", "outputs": {}}]]],
    "count": [
        [["state_set", {"key": "colour", "value": "red"}]],
        {"crash": True},
        [["state_get", {"key": "colour"}]],
        [["exit", {"outcome": "done", "outputs": {"total": 1}}]],
    ],
}
JOB = "import sys; sys.path.insert(0, sys.argv[1]); import script_model; from agent_core.cli import main; sys.exit(main(sys.argv[2:]))"


@pytest.fixture
def scripts(tmp_path, monkeypatch):
    directory = tmp_path / "scripts"
    directory.mkdir()
    for node, steps in SCRIPTS.items():
        (directory / f"{node}.json").write_text(json.dumps(steps))
    monkeypatch.setenv("AGENT_CORE_LANGGRAPH_MODEL", f"script:{directory}")
    return directory


async def test_a_fragment_resumes_inside_its_running_node_with_its_values(scripts, tmp_path):
    run = tmp_path / "runs" / RUN_ID
    died = subprocess.run(
        [sys.executable, "-c", JOB, str(CONFORMANCE), "job", str(INSTANCE), "singles", "--backend", "langgraph",
         "--run-dir", str(run), "--input", "name=alpha"],
        env=os.environ, capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL,
    )
    assert died.returncode != 0 and list(scripts.glob("count.*.progress.json")), died.stderr[-2000:]   # it ended in `count`
    assert (run / "checkpoints.sqlite").exists()

    async with agent_core.open(INSTANCE, backend="langgraph", runs=tmp_path / "runs") as harness:
        result = await harness.sequences.resume(RUN_ID)
        events = harness.events.record()
    assert (result.end, result.facts["total"]) == ("done", 1)
    assert [e.node for e in events if isinstance(e, NodeStarted)] == ["count"]   # `lookup` finished before the crash
    assert [e.text for e in events if isinstance(e, ToolReturned) and e.call.name == "state_get"] == ['"red"']   # the value came back
    [step] = result.steps   # the fragment is one macro step, with its inner steps listed
    assert (step["name"], step["outcome"], [s["name"] for s in step["steps"]]) == ("single", "done", ["lookup", "count"])


SECOND_RUN = "import sys; sys.path.insert(0, sys.argv[1]); import script_model, elsewhere, asyncio; import agent_core.backends.langgraph.fragments as f; f.RETRY_PAUSE = 0; asyncio.run(elsewhere.main(*sys.argv[2:]))"


async def test_a_resume_continues_the_second_run_of_an_item_and_does_not_enter_the_first_again(tmp_path, monkeypatch):   # RTY-2, §4.4a
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    steps = {
        # the first run is refused; the second, on its own thread, passes over the refusal and dies; the resumed second run goes on
        "lookup": [{"raise": "passes", "once": True}, {"crash": True}, [["lookup_revision", {}]], [["exit", {"outcome": "done", "outputs": {}}]]],
        "count": [[["exit", {"outcome": "done", "outputs": {"total": 7}}]]],
    }
    for node, script in steps.items():
        (scripts / f"{node}.json").write_text(json.dumps(script))
    monkeypatch.setenv("AGENT_CORE_LANGGRAPH_MODEL", f"script:{scripts}")
    monkeypatch.setenv("AGENT_CORE_LANGGRAPH_MAX_RETRIES", "0")
    run_id = "pairs-20261119T000000Z-abc123"
    died = subprocess.run(
        [sys.executable, "-c", SECOND_RUN, str(CONFORMANCE), str(INSTANCE), "langgraph", str(tmp_path / "runs"), "pairs", run_id,
         json.dumps({"names": ["alpha"]})],
        env=os.environ, capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL,
    )
    assert died.returncode != 0 and len(list(scripts.glob("lookup.*.progress.json"))) == 2, died.stderr[-2000:]   # both runs reached the model

    async with agent_core.open(INSTANCE, backend="langgraph", runs=tmp_path / "runs") as harness:
        result = await harness.sequences.resume(run_id)
        events = harness.events.record()
    # entering the first run again would have played its crash step: its conversation has a refusal and a crash behind it
    assert (result.end, result.facts["revisions"], result.facts["revisions_failures"]) == ("done", [{"revision": "r1"}], [])
    assert [e.node for e in events if isinstance(e, NodeStarted)] == ["lookup", "count"]
