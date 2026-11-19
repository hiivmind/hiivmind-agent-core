import pytest
from audit import DESELECTED, RAN, all_matrices, problems

from agent_core.contracts.matrix import Entry, Feature

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


def test_every_registered_backend_passes_the_audit():   # MTX-1, MTX-2
    if DESELECTED:
        pytest.skip("the audit needs the whole conformance suite in the same session")
    assert problems(all_matrices(), RAN) == []
