"""The `summary` context strategy: a node starts with one note that summarises the session so far (NODE-15, CTX-4)."""

from agent_core.contracts.context import HandoverRequest, transcript_handover
from agent_core.contracts.registry import register
from agent_core.contracts.values import Message

INSTRUCTIONS = (
    "Summarise this session between a person and an agent in a few sentences. Keep each name, value and preference the "
    "person gave. Reply with the summary only."
)


@register("context", "summary")
class SummaryStrategy:
    async def build(self, request: HandoverRequest) -> tuple[Message, ...]:
        if not request.transcript:
            return ()
        text = "\n".join(f"{m.kind}: {m.text}" for m in transcript_handover(request.transcript))
        summary = await request.summarise(INSTRUCTIONS, text)
        return (Message("user", f"(The harness: a summary of the session so far. {summary})"),)
