"""F13 caching: the backend asks the provider's own cache middleware to wrap each model call, and what the provider
reports of the cache reaches the record.

Offline the observable is a provider module of the test's own whose cache middleware is a marker: it must see every model
call of the node, and the cache counts the model reports must come out in the node's note.
"""

from pathlib import Path

import pytest
from langchain.agents.middleware import AgentMiddleware
from script_model import ScriptChatModel, ScriptProvider

from agent_core.contracts.registry import register

EXIT = [["exit", {"outcome": "done", "outputs": {}}]]
LOOKUP = [["lookup_revision", {"name": "alpha"}]]
SEEN: list[str] = []


class Marker(AgentMiddleware):
    async def awrap_model_call(self, request, handler):
        SEEN.append("a model call")
        return await handler(request)


class CachingProvider(ScriptProvider):
    name = "caching"

    def chat_model(self, model: str, settings):
        return ScriptChatModel(directory=Path(self.directory))

    def cache_middleware(self) -> list:
        return [Marker()]


register("model_provider", "caching")(CachingProvider())


@pytest.mark.feature("F13")
async def test_the_providers_cache_middleware_wraps_each_model_call_and_its_counts_reach_the_note(harness):
    SEEN.clear()
    h = harness({"lookup": [
        {"calls": LOOKUP, "usage": {"input_tokens": 100, "input_token_details": {"cache_read": 0, "cache_creation": 60}}},
        {"calls": EXIT, "usage": {"input_tokens": 120, "input_token_details": {"cache_read": 60, "cache_creation": 0}}},
    ]}, delivery={"model": "caching:any-model"})
    outcome = await h.nodes.run("lookup", {"name": "alpha"})
    assert len(SEEN) == 2
    [note] = outcome.notes
    assert (note.usage.sent, note.usage.cache_read, note.usage.cache_written) == (220, 60, 60)


@pytest.mark.feature("F13")
async def test_a_provider_with_no_cache_middleware_runs_the_same_node(harness):
    outcome = await harness({"lookup": [LOOKUP, EXIT]}).nodes.run("lookup", {"name": "alpha"})
    assert outcome.exit == "done"
