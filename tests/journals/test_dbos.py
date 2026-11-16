"""The `dbos` journal (design §4.7), through a harness process per run."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parent / "dbos_harness.py"
STEPS = [[1, "a"], [2, "b[1]"], [3, "b[2]"], [4, "c"]]


@pytest.fixture
def harness(tmp_path):
    """`harness(mode, run_id, *args)` runs one process; returns (exit code, its JSON line or {}, the steps it ran)."""

    def run(mode, run_id, *args):
        log = tmp_path / f"{run_id}-{mode}.log"
        done = subprocess.run(
            [sys.executable, str(HARNESS), mode, "--db", str(tmp_path / "journal.sqlite"), "--id", run_id, "--log", str(log), *args],
            capture_output=True, text=True, timeout=120,
        )
        lines = done.stdout.strip().splitlines()
        out = json.loads(lines[-1]) if lines and lines[-1].startswith("{") else {}
        ran = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return done.returncode, out, ran

    return run


def test_a_run_records_its_steps_in_order(harness):                                       # RESUME-2
    code, out, ran = harness("start", "r1")
    assert code == 0 and [s[:2] for s in out["steps"]] == STEPS
    assert out["result"] == {"name": "toy", "facts": {"x": 1}, "results": ["A", "B[1]", "B[2]", "C"]}


def test_a_step_given_a_lambda_records_the_awaited_result(harness):
    code, out, ran = harness("start", "r1")
    assert [s[2] for s in out["steps"]] == ["A", "B[1]", "B[2]", "C"]


def test_resume_after_a_crash_runs_the_rest_on_the_runs_own_loop(harness):                # RESUME-3
    code, _, ran = harness("start", "r1", "--crash", "c")
    assert code == 3 and [r["step"] for r in ran] == ["a", "b[1]", "b[2]", "c"]
    code, out, ran = harness("resume", "r1")
    assert code == 0 and out["result"]["results"] == ["A", "B[1]", "B[2]", "C"]
    assert [(r["step"], r["main_loop"]) for r in ran] == [("c", True)]


def test_resume_of_a_run_that_raised_raises_it_again(harness):                            # design §4.7
    code, out, _ = harness("start", "r1", "--fail", "c")
    assert out["error"] == "RuntimeError: c broke"
    code, out, ran = harness("resume", "r1")
    assert out["error"] == "RuntimeError: c broke" and ran == []


def test_resume_of_a_finished_run_returns_its_result(harness):                            # design §4.7
    harness("start", "r1")
    code, out, ran = harness("resume", "r1")
    assert out["result"]["results"] == ["A", "B[1]", "B[2]", "C"] and ran == []


def test_rerun_from_step_3_runs_b2_and_c(harness):                                        # RESUME-5
    harness("start", "r1")
    code, out, ran = harness("rerun", "r2", "--source", "r1", "--step", "3")
    assert code == 0 and [(r["step"], r["main_loop"]) for r in ran] == [("b[2]", True), ("c", True)]
    assert [s[:2] for s in out["steps"]] == STEPS and out["result"]["results"] == ["A", "B[1]", "B[2]", "C"]
