"""`Macro`: the walk driven over backends, a journal, and units named by thread and intent (architecture §4.4a)."""

import dataclasses
import subprocess
import sys
from pathlib import Path

import pytest
from macro_support import RESULTS, Toy, make_unit, no_check, no_tool, topology

from agent_core.contracts.registry import provider
from agent_core.contracts.unit import UnitResult
from agent_core.core.macro import Macro

HARNESS = Path(__file__).resolve().parent / "macro_harness.py"


def macro_of(toy, journal, topo=None, pause=0):
    topo = topo or topology()
    return Macro(topo, backends=lambda name: toy, default_backend="toy", make_unit=make_unit(topo),
                 journal=journal, call_tool=no_tool, check=no_check, pause=pause)


@pytest.fixture
def none_journal():
    return provider("journal", "none")()


async def test_each_unit_runs_on_a_thread_named_by_run_step_item_and_attempt(tmp_path, none_journal):   # ORC-6
    toy = Toy(tmp_path / "units.log")
    result = await macro_of(toy, none_journal).start("r1", "fan", {})
    assert result["end"] == "done"
    assert [u.thread for u in toy.units] == ["r1/1/0/1", "r1/2/1/1", "r1/3/2/1"]
    assert [u.name for u in toy.units] == ["update-sources", "scan", "scan"]
    assert {u.intent for u in toy.units} == {"start"}


async def test_a_fragment_is_one_macro_step_with_its_inner_steps_listed(tmp_path, none_journal):   # RESUME-2, example 2
    toy = Toy(tmp_path / "units.log")
    result = await macro_of(toy, none_journal).start("r1", "with-tail", {})
    assert [s["name"] for s in result["trail"]] == ["first", "tail"]
    assert [s["name"] for s in result["trail"][1]["steps"]] == ["wrap", "close"]
    assert [(u.name, u.thread) for u in toy.units] == [("first", "r1/1/0/1"), ("tail", "r1/2/0/1")]
    assert toy.units[1].fragment is not None and toy.units[0].fragment is None


async def test_nothing_resumes_unless_resume_is_called(tmp_path, none_journal):   # RESUME-4
    toy = Toy(tmp_path / "units.log")
    macro = macro_of(toy, none_journal)
    await macro.start("r1", "with-tail", {})
    await macro.start("r2", "with-tail", {})
    assert {u.intent for u in toy.units} == {"start"}


class Refusing(Toy):
    """The first run of `scan` is refused as unavailable; the walk's second run is `fresh`."""

    async def run_node(self, unit):
        from agent_core.contracts.errors import ProviderUnavailable

        self._record(unit)
        if unit.name == "scan" and unit.thread.endswith("/1"):
            raise ProviderUnavailable("down")
        return RESULTS[unit.name]


async def test_the_walks_fresh_second_run_keeps_its_intent_and_attempt(tmp_path, none_journal):
    toy = Refusing(tmp_path / "units.log")
    macro = macro_of(toy, none_journal, dataclasses.replace(topology()))
    await macro.start("r1", "fan", {})
    assert [(u.thread, u.intent) for u in toy.units if u.name == "scan"][:3] == [
        ("r1/2/1/1", "start"), ("r1/2/1/2", "fresh"), ("r1/3/2/1", "start"),
    ]


def die_in_tail(tmp_path, journal_file):
    log = tmp_path / "first.log"
    done = subprocess.run(
        [sys.executable, str(HARNESS), str(journal_file), "r1", str(log), "with-tail", "--die-in", "tail"],
        capture_output=True, text=True, timeout=120,
    )
    return done.returncode, Toy(log).logged()


async def test_a_resumed_run_reenters_the_running_step_with_continue(tmp_path):   # Review Focus 2
    journal_file = tmp_path / "journal.sqlite"
    code, first = die_in_tail(tmp_path, journal_file)
    assert code == 3
    assert [(u["name"], u["intent"], u["thread"]) for u in first] == [("first", "start", "r1/1/0/1"), ("tail", "start", "r1/2/0/1")]
    toy = Toy(tmp_path / "second.log")
    journal = provider("journal", "dbos")(journal_file, "macro", "r1")
    try:
        result = await macro_of(toy, journal).resume("r1")
    finally:
        await journal.close()
    assert [(u.name, u.intent, u.thread) for u in toy.units] == [("tail", "continue", "r1/2/0/1")]   # `first` is not run again
    assert result["end"] == "done" and [s["name"] for s in result["trail"]] == ["first", "tail"]
    assert result["facts"]["first_done"] == "yes" and result["facts"]["closed"] == "yes"


async def test_a_resumed_run_sees_the_unit_result_a_finished_step_recorded(tmp_path):
    journal_file = tmp_path / "journal.sqlite"
    die_in_tail(tmp_path, journal_file)
    toy = Toy(tmp_path / "second.log")
    journal = provider("journal", "dbos")(journal_file, "macro", "r1")
    try:
        result = await macro_of(toy, journal).resume("r1")
        from dbos import DBOS

        recorded = {s["function_name"]: s["output"] for s in await DBOS.list_workflow_steps_async("r1")}
    finally:
        await journal.close()
    assert result["trail"][0] == {"step": 1, "name": "first", "outcome": "done"}
    assert result["facts"]["first_done"] == "yes"   # from the `UnitResult` of `first`, run by the first process
    assert recorded["first"] == RESULTS["first"]   # DBOS gives back the `UnitResult` it was given
