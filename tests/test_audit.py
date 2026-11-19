import pytest
from audit import DESELECTED, RAN, all_matrices, problems, record
from pydantic import ValidationError
from pydantic_settings import BaseSettings

from agent_core.contracts.matrix import Entry, Feature
from agent_core.contracts.registry import REGISTERED_BACKENDS
from agent_core.core.registry import BACKENDS

FULL = {feature: Entry("helper", "toy") for feature in Feature}
RAN_WITHOUT_F12 = {("toy", feature.id) for feature in Feature if feature is not Feature.F12}


def test_a_native_entry_without_conformance_tests_fails_the_audit():   # example 7
    matrix = {**FULL, Feature.F12: Entry("native", "x")}
    assert problems({"toy": matrix}, RAN_WITHOUT_F12) == ["backend toy declares F12 native but its conformance tests do not run"]


def test_a_feature_whose_only_test_skipped_at_runtime_fails_the_audit():   # MTX-2
    matrix = {**FULL, Feature.F12: Entry("helper", "x")}   # a test that skipped at runtime is not in `ran`
    assert problems({"toy": matrix}, RAN_WITHOUT_F12) == ["backend toy declares F12 helper but its conformance tests do not run"]


def test_a_feature_not_built_or_divergent_needs_no_test_that_ran():
    for state in ("not built", "divergent"):
        assert problems({"toy": {**FULL, Feature.F12: Entry(state, "x")}}, RAN_WITHOUT_F12) == []


def test_a_missing_entry_fails_the_audit():   # MTX-1
    matrix = {feature: entry for feature, entry in FULL.items() if feature is not Feature.F20}
    assert problems({"toy": matrix}, {("toy", feature.id) for feature in Feature}) == ["backend toy has no entry for F20"]


def test_each_backend_is_audited_on_its_own_pairs():
    ran = {("a", feature.id) for feature in Feature}
    assert problems({"a": FULL, "b": FULL}, ran) == [
        f"backend b declares {feature.id} helper but its conformance tests do not run" for feature in Feature
    ]


def test_a_backend_whose_settings_need_a_value_still_gives_its_matrix(monkeypatch):
    class NeedsAModel(BaseSettings):
        MODEL: str   # no default: the settings cannot be made without one

    class Toy:
        FEATURES = FULL

        def __init__(self, settings):
            raise AssertionError("the audit makes no backend")

    monkeypatch.delenv("MODEL", raising=False)   # these settings have no env prefix: a MODEL in the environment would fill it
    with pytest.raises(ValidationError):
        NeedsAModel()
    monkeypatch.setitem(REGISTERED_BACKENDS, "toy", (Toy, NeedsAModel))
    monkeypatch.setitem(BACKENDS, "toy", ("toy_module", ""))
    assert all_matrices()["toy"] == FULL


# --- which conformance tests count as run -------------------------------------------------------------------------------

PAIRS = [("toy", "F1")]


def report(when, outcome, **extra):
    return pytest.TestReport("tests/conformance/test_f01_loop.py::t[toy]", ("", 0, ""), {}, outcome, None, when, **extra)


def counted(setup="passed", call="passed", teardown="passed", wasxfail=None) -> bool:
    ran: set = set()
    extra = {} if wasxfail is None else {"wasxfail": wasxfail}
    for when, outcome in (("setup", setup), ("call", call), ("teardown", teardown)):
        record(report(when, outcome, **(extra if when == "call" else {})), PAIRS, ran)
    return ran == set(PAIRS)


def test_a_test_that_passed_in_each_phase_counts_as_run():
    assert counted()


def test_a_skip_in_any_phase_does_not_count_as_run():
    assert not counted(setup="skipped")
    assert not counted(call="skipped")
    assert not counted(teardown="skipped")


def test_a_failure_in_any_phase_does_not_count_as_run():
    assert not counted(setup="failed")
    assert not counted(call="failed")
    assert not counted(teardown="failed")


def test_a_strict_xfail_counts_as_run_and_a_strict_xpass_does_not():
    assert counted(call="skipped", wasxfail="divergent")   # a strict xfail that failed as expected is reported skipped
    assert not counted(call="failed")                      # a strict xfail that passed is reported failed


def test_a_test_whose_call_never_ran_does_not_count_as_run():
    ran: set = set()
    record(report("setup", "skipped"), PAIRS, ran)         # a `skip` mark: setup is skipped and there is no call phase
    record(report("teardown", "passed"), PAIRS, ran)
    assert ran == set()


def test_every_registered_backend_passes_the_audit():   # MTX-1, MTX-2
    if DESELECTED:
        pytest.skip("the audit needs the whole conformance suite in the same session")
    assert problems(all_matrices(), RAN) == []
