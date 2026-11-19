"""The `none` context strategy: a node starts without the earlier conversation. A job's node always gets it."""

from agent_core.contracts.context import HandoverRequest
from agent_core.contracts.registry import register
from agent_core.contracts.values import Message


@register("context", "none")
class NoneStrategy:
    async def build(self, request: HandoverRequest) -> tuple[Message, ...]:
        return ()
