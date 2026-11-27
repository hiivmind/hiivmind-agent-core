"""The `all` context strategy: a node starts with the session's whole transcript (NODE-15, CTX-5)."""

from agent_core.contracts.context import HandoverRequest, transcript_handover
from agent_core.contracts.registry import register
from agent_core.contracts.values import Message


@register("context", "all")
class AllStrategy:
    async def build(self, request: HandoverRequest) -> tuple[Message, ...]:
        return transcript_handover(request.transcript)
