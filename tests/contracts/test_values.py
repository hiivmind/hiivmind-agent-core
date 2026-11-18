from agent_core.contracts.errors import FeatureNotSupported, ToolServerError
from agent_core.contracts.matrix import Entry, Feature
from agent_core.contracts.topology import NodeContract
from agent_core.contracts.values import BUILT_IN_OUTCOMES, HARNESS_REASONS
from agent_core.contracts.walk import RETRY_PAUSE, WalkResult


def test_feature_not_supported_names_the_feature_backend_and_reason():
    e = FeatureNotSupported(Feature.F19, "toy", Entry("divergent", "its SDK has no event stream"))
    assert str(e) == "streaming is divergent on backend toy: its SDK has no event stream"


def test_a_walk_result_is_a_typed_dict_with_the_four_keys():
    assert set(WalkResult.__annotations__) == {"end", "trail", "facts", "summary"}


def test_a_contracts_outcomes_add_the_built_ins_once():
    assert NodeContract("n", (), (), ("done", "stopped")).outcomes == ("done", "stopped", "skipped")


def test_fixed_values():
    assert BUILT_IN_OUTCOMES == ("skipped", "stopped")
    assert HARNESS_REASONS == ("needs_input", "invalid_output", "no_exit", "unknown_placeholder", "precondition_unmet")
    assert RETRY_PAUSE == 60


def test_tool_server_error_message():
    e = ToolServerError("srv", "t", "boom")
    assert (e.server, e.tool) == ("srv", "t")
    assert str(e) == "tool server `srv` did not answer the call to `t`: boom"
