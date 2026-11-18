"""A NodeController test double that records what it is asked."""

import pytest

from agent_core.contracts import EndRun, ModelResponse, Result, ToolCall


class Recorder:
    def __init__(self):
        self.events: list[tuple] = []
        self.end_on: str | None = None
        self.reply: str | None = None

    def ending_on(self, name: str) -> "Recorder":
        self.end_on = name
        return self

    def replying(self, text: str | None) -> "Recorder":
        self.reply = text
        return self

    async def handle(self, call: ToolCall):
        self.events.append(("handle", call.name))
        return EndRun() if call.name == self.end_on else Result("ok")

    async def responded(self, response: ModelResponse) -> None:
        self.events.append(("responded", tuple(c.name for c in response.calls)))
        self.last_response = response

    async def stopped(self, said: str) -> str | None:
        self.events.append(("stopped", said))
        return self.reply


@pytest.fixture
def recorder():
    return Recorder()
