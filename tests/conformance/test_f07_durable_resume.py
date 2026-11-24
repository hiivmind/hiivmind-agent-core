"""F7 durable resume: a run that died is resumed by its id, and the steps it finished are not run again.

What a unit in flight does on resume is the backend's own (the scripted backend runs it again from its start), so it
is not part of this suite.
"""

import pytest

from agent_core.contracts.events import NodeStarted

FIRST = [[["lookup_revision", {}]], [["exit", {"outcome": "done", "outputs": {}}]]]
SECOND = [[["crash_once", {}]], [["exit", {"outcome": "done", "outputs": {"total": 1}}]]]


@pytest.mark.feature("F7")
async def test_finished_steps_are_not_run_again_on_resume(harness, elsewhere, tmp_path, fixture_run_dir):
    scripts = {"lookup": FIRST, "count": SECOND}
    run = tmp_path / "runs" / "lookup_then_count-20261119T000000Z-abc123"
    run.mkdir(parents=True)
    marker = fixture_run_dir / "crash-once"   # `crash_once` is a function: it reads the directory the test gave it (Q5)
    marker.write_text("")
    died = elsewhere(scripts, "lookup_then_count", run.name, {"name": "alpha"})
    assert died.returncode == 3, died.stderr[-2000:]
    assert not marker.exists()   # the second node ran, and ended the process in `crash_once`

    resumed = harness(scripts)
    result = await resumed.sequences.resume(run.name)
    assert (result.end, result.facts["revision"], result.facts["total"]) == ("done", "r1", 1)
    started = [e.node for e in resumed.events.record() if isinstance(e, NodeStarted)]
    assert started == ["count"]   # `lookup` finished in the first process and is not run again
