"""F12 retries: the backend retries a model call the provider refused in a way that passes, once, and says what it cannot retry.

A step `{"raise": kind}` of the script is a refused model call. The backend's one retry owner decides from the provider
module's classification; the client's own retries are off (checked on each provider module in tests/backends/langgraph).
"""

import pytest

from agent_core.contracts.errors import ProviderRefused, ProviderUnavailable
from agent_core.contracts.events import ModelRequested, ModelResponded

EXIT = [["exit", {"outcome": "done", "outputs": {}}]]
LOOKUP = [["lookup_revision", {"name": "alpha"}]]


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    """The retries' backoff is not waited for: the middleware's delay is made zero."""
    monkeypatch.setattr("langchain.agents.middleware.model_retry.calculate_delay", lambda *a, **k: 0)


def model_calls(tmp_path, h) -> int:
    """The calls the model received: the answers it gave and the refusals it played (the script counts them on disk)."""
    refused = sum(int(f.read_text()) for f in tmp_path.glob("scripts-*/*.progress.json"))
    return refused + sum(isinstance(e, ModelResponded) for e in h.events.record())


@pytest.mark.feature("F12")
async def test_a_refusal_that_passes_is_retried_by_the_middleware_only(harness, tmp_path):
    h = harness({"lookup": [{"raise": "passes"}, {"raise": "passes"}, LOOKUP, EXIT]})
    outcome = await h.nodes.run("lookup", {"name": "alpha"})
    assert outcome.exit == "done"
    assert sum(isinstance(e, ModelRequested) for e in h.events.record()) == 4   # every attempt sent is a request (CTX-6)
    assert model_calls(tmp_path, h) == 4   # two refused, two answered (the lookup and the exit): no second owner multiplied the attempts


@pytest.mark.feature("F12")
async def test_a_refusal_that_will_not_pass_is_not_retried_and_reaches_the_core_as_provider_refused(harness, tmp_path):
    h = harness({"lookup": [{"raise": "will not pass"}, LOOKUP, EXIT]})
    with pytest.raises(ProviderRefused) as caught:
        await h.nodes.run("lookup", {"name": "alpha"})
    assert str(caught.value) == "the provider refused: scripted refusal that will not pass"
    assert model_calls(tmp_path, h) == 1


@pytest.mark.feature("F12")
async def test_exhausted_retries_raise_provider_unavailable(harness, tmp_path, monkeypatch):    # RTY-2a
    monkeypatch.setenv("AGENT_CORE_LANGGRAPH_MAX_RETRIES", "2")
    h = harness({"lookup": [{"raise": "passes"}] * 4 + [LOOKUP, EXIT]})
    with pytest.raises(ProviderUnavailable) as caught:
        await h.nodes.run("lookup", {"name": "alpha"})
    assert str(caught.value) == "ScriptRefusal: scripted refusal that passes"
    assert type(caught.value.__cause__).__name__ == "ScriptRefusal"
    assert model_calls(tmp_path, h) == 3   # the call and two retries


@pytest.mark.feature("F12")
async def test_an_error_that_is_not_a_refusal_is_not_retried_and_is_not_mapped(harness, tmp_path):
    h = harness({"lookup": [{"raise": "other"}, LOOKUP, EXIT]})
    with pytest.raises(Exception) as caught:
        await h.nodes.run("lookup", {"name": "alpha"})
    assert type(caught.value).__name__ == "ScriptRefusal"
    assert model_calls(tmp_path, h) == 1
