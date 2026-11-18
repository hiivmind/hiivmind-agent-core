"""Sequence jobs on the command line: `agent-core job <instance> <sequence>`, resume and re-run (design §4.6, §4.7)."""

import json
import sqlite3

DONE_STEPS = [
    (1, "checks"), (2, "update-sources"), (3, "scan[1]"), (4, "scan[2]"), (5, "scan[3]"), (6, "index"), (7, "verify"),
    (8, "publish"),
]


def journal_steps(run_dir, run_id):
    """(number, name) of each step DBOS recorded for the run, read from the journal beside the run directory."""
    with sqlite3.connect(run_dir.parent / "journal.sqlite") as db:
        rows = db.execute(
            "select function_id, function_name from operation_outputs where workflow_uuid = ? order by function_id", (run_id,)
        ).fetchall()
    return [tuple(row) for row in rows]


def journal_status(run_dir, run_id):
    with sqlite3.connect(run_dir.parent / "journal.sqlite") as db:
        return db.execute("select status from workflow_status where workflow_uuid = ?", (run_id,)).fetchone()[0]


def numbered(record):
    return [(s["step"], s["name"]) for s in record["steps"] if s["step"] is not None]


def ran(record):
    """The nodes this process ran, in the order they started."""
    return [run["node"] for run in record["runs"]]


def calls(run_dir):
    file = run_dir / "calls.jsonl"
    return [json.loads(line) for line in file.read_text().splitlines()] if file.exists() else []


def test_a_sequence_job_runs_and_records_its_steps(seq_job):                               # JOB-14, RESUME-1, RESUME-2
    done = seq_job("refresh")
    assert done.code == 0 and done.out.splitlines()[0] == "run run"
    record = done.record
    assert (record["run_id"], record["end_state"], record["status"]) == ("run", "done", "ok")
    assert numbered(record) == DONE_STEPS == journal_steps(done.run_dir, "run")
    assert record["summary"] == {"pr_url": "https://example.org/pr/1"} and record["facts"]["drift"] == 0


def test_already_current_needs_no_model(seq_job):                                         # criterion 1
    done = seq_job("refresh", env={"SEQ_REFRESH_NEEDED": "0"})
    assert done.code == 0 and done.record["summary"] == "Already current." and done.record["model_calls"] == 0
    assert numbered(done.record) == [(1, "checks")]


def test_a_sequence_that_ends_failed_exits_one(seq_job):                                  # JOB-17
    done = seq_job("refresh", scripts={"verify": [[["exit", {"outcome": "failed", "outputs": {"reason": "drift"}}]]]})
    assert done.code == 1 and (done.record["end_state"], done.record["status"]) == ("failed", "failed")
    assert done.record["summary"] == {"reason": "drift"}


def test_a_sequence_that_ends_stopped_exits_zero(seq_job):                                # JOB-17, SEQ-7
    done = seq_job("refresh", scripts={"verify": [[["exit", {"outcome": "stopped", "outputs": {}}]]]})
    assert done.code == 0 and done.record["end_state"] == "stopped" and "publish" not in ran(done.record)


def test_a_name_that_is_both_stops_the_run(seq_job):                                      # JOB-15
    done = seq_job("refresh", files={"jobs/refresh.py": "async def main(job):\n    return 1\n"})
    assert done.code == 2 and done.out == "error: `refresh` is both a job script and a sequence\n"


def test_an_unknown_name_lists_sequences_and_scripts(seq_job):                            # §4.6
    done = seq_job("nope", files={"jobs/tidy.py": "async def main(job):\n    return 1\n"})
    assert done.code == 2 and done.out.startswith("error: no sequence or job script `nope`")
    assert "chain, enrich, graph, migrate, refresh, status" in done.out and "tidy" in done.out


def test_input_reaches_the_node(seq_job):                                                 # JOB-16
    done = seq_job("graph", args=["--input", "action=validate"])
    assert done.code == 0
    assert [json.loads(line) for line in (done.run_dir / "inputs.jsonl").read_text().splitlines()] == [{"action": "validate"}]


def test_resume_after_a_crash_runs_only_what_did_not_finish(seq_job):                     # RESUME-3
    crashed = seq_job("refresh", env={"SEQ_CRASH": "verify"})
    assert crashed.code == 3 and crashed.record == {}
    done = seq_job("refresh", args=["--resume", "run"])
    assert done.code == 0 and ran(done.record) == ["verify", "publish"]
    assert numbered(done.record) == DONE_STEPS and done.record["end_state"] == "done"


def test_resume_after_a_crash_in_a_fan_out_repeats_only_unfinished_scans(seq_job):        # RESUME-3, FAN-7
    crashed = seq_job("refresh", env={"SEQ_CRASH": "scan", "SEQ_CRASH_AT": "2"})
    assert crashed.code == 3
    done = seq_job("refresh", args=["--resume", "run"])
    assert done.code == 0 and ran(done.record) == ["scan", "scan", "index", "verify", "publish"]


def test_a_new_run_does_not_resume_a_crashed_one(seq_job):                                # RESUME-4
    crashed = seq_job("refresh", env={"SEQ_CRASH": "verify"})
    assert crashed.code == 3
    done = seq_job("refresh", run="second")
    assert done.code == 0 and ran(done.record)[0] == "update-sources"
    assert journal_status(crashed.run_dir, "run") == "PENDING"


def test_rerun_from_a_step(seq_job):                                                      # RESUME-5
    seq_job("refresh")
    done = seq_job("refresh", run="again", args=["--rerun-from", "run:6"])
    assert done.code == 0 and done.out.splitlines()[0] == "run again (from run, step 6)"
    assert done.record["run_id"] == "again" and ran(done.record) == ["index", "verify", "publish"]
    assert journal_steps(done.run_dir, "again") == DONE_STEPS


def test_a_crashed_rerun_resumes_by_its_printed_id(seq_job):                              # RESUME-5, RESUME-3
    seq_job("refresh")
    crashed = seq_job("refresh", run="again", args=["--rerun-from", "run:7"], env={"SEQ_CRASH": "verify"})
    assert crashed.code == 3
    done = seq_job("refresh", run="again", args=["--resume", "again"])
    assert done.code == 0 and ran(done.record) == ["verify", "publish"]


def test_resume_of_a_run_that_raised_exits_one(seq_job):                                  # design §4.7, example 9
    first = seq_job("refresh", scripts={"verify": None})
    assert first.code == 1 and first.record["summary"].startswith("NodeRunError: verify#")
    done = seq_job("refresh", args=["--resume", "run"])
    assert done.code == 1 and done.record["summary"] == first.record["summary"] and ran(done.record) == []
    assert first.record["summary"] in done.out


def test_a_run_that_raised_keeps_the_steps_it_took(seq_job):                              # §4.6, RESUME-2, example 9
    first = seq_job("refresh", scripts={"verify": None})
    record = first.record
    assert record["end_state"] == "failed" and record["facts"]["entries"] == ["e1", "e2"]
    assert numbered(record) == DONE_STEPS[:7] and record["steps"][-1] == {"step": 7, "name": "verify", "outcome": None}


def test_resume_of_an_unknown_run_fails_with_dboss_error(seq_job):                        # Review Focus 3
    done = seq_job("refresh", args=["--resume", "nosuchrun"])
    assert done.code == 1 and "nosuchrun" in done.out and ran(done.record) == []


def test_two_sequence_jobs_at_once_share_the_journal(seq_job):                            # Review Focus 1
    started = [seq_job.start("refresh", run=run) for run in ("one", "two")]
    for child, _ in started:
        child.communicate(timeout=300)
        assert child.returncode == 0
    records = [json.loads((run_dir / "record.json").read_text()) for _, run_dir in started]
    assert [r["run_id"] for r in records] == ["one", "two"] and all(r["end_state"] == "done" for r in records)


def test_a_resume_runs_in_its_own_process_while_another_job_runs(seq_job):                # plan review, finding 1
    crashed = seq_job("refresh", env={"SEQ_CRASH": "verify", "SEQ_LABEL": "A"})
    assert crashed.code == 3
    other, other_dir = seq_job.start("refresh", run="other", env={"SEQ_LABEL": "B", "SEQ_SLOW": "1"})
    done = seq_job("refresh", args=["--resume", "run"], env={"SEQ_LABEL": "A"})
    other.communicate(timeout=300)
    assert done.code == 0 and other.returncode == 0
    resumed = calls(done.run_dir)[-2:]
    assert [(c["node"], c["label"]) for c in resumed] == [("verify", "A"), ("publish", "A")]
    assert {c["label"] for c in calls(other_dir)} == {"B"} and len(calls(other_dir)) == 5
