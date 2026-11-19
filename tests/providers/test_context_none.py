from agent_core.context.none import NoneStrategy
from agent_core.contracts.context import HandoverRequest
from agent_core.contracts.topology import NodeContract
from agent_core.contracts.values import Message
from agent_core.core.registry import provider


async def _no_summary(system: str, text: str) -> str:
    raise AssertionError("the none strategy summarises nothing")


def test_the_none_strategy_is_found_by_name():
    assert provider("context", "none") is NoneStrategy


async def test_a_node_starts_without_the_earlier_conversation():   # CTX-3
    request = HandoverRequest(
        transcript=(Message("user", "earlier"),), facts={"a": 1}, node="scan", inputs={}, contract=NodeContract("scan", (), (), ()),
        summarise=_no_summary,
    )
    assert await NoneStrategy().build(request) == ()
