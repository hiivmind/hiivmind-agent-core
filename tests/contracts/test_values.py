import dataclasses
import inspect

import pytest

from agent_core.contracts.context import HandoverRequest
from agent_core.contracts.person import Person
from agent_core.contracts.errors import FeatureNotSupported, ToolServerError
from agent_core.contracts.matrix import Entry, Feature
from agent_core.contracts.topology import NodeContract
from agent_core.contracts.values import BUILT_IN_OUTCOMES, DONE, FAILED, HarnessReason
from agent_core.contracts.walk import RETRY_PAUSE, WalkResult


def test_feature_not_supported_names_the_feature_backend_and_reason():
    e = FeatureNotSupported(Feature.F19, "toy", Entry("divergent", "its SDK has no event stream"))
    assert str(e) == "streaming is divergent on backend toy: its SDK has no event stream"


def test_a_walk_result_is_a_typed_dict_with_its_keys():
    assert set(WalkResult.__annotations__) == {"end", "trail", "facts", "summary", "sequence", "outputs"}


def test_a_contracts_outcomes_add_the_built_ins_once():
    assert NodeContract("n", (), (), ("done", "stopped")).outcomes == ("done", "stopped", "skipped")


def test_fixed_values():
    assert BUILT_IN_OUTCOMES == ("skipped", "stopped")
    assert [r.value for r in HarnessReason] == [
        "needs_input", "invalid_output", "no_exit", "unknown_placeholder", "precondition_unmet", "no_transition"]
    assert (DONE, FAILED) == ("done", "failed")
    assert RETRY_PAUSE == 60


def test_tool_server_error_message():
    e = ToolServerError("srv", "t", "boom")
    assert (e.server, e.tool) == ("srv", "t")
    assert str(e) == "tool server `srv` did not answer the call to `t`: boom"


def test_feature_value_is_its_id_and_looks_up_by_id():
    assert Feature.F1.value == "F1"
    assert Feature("F19") is Feature.F19 and Feature("F19").title == "streaming"


def test_handover_request_is_frozen():
    async def summarise(a: str, b: str) -> str:
        return a + b
    h = HandoverRequest((), {}, "n", {}, NodeContract("n", (), (), ("done",)), summarise)
    with pytest.raises(dataclasses.FrozenInstanceError):
        h.node = "x"


def test_person_ask_takes_a_question():                                                     # RP-8
    assert list(inspect.signature(Person.ask).parameters) == ["self", "question"]
