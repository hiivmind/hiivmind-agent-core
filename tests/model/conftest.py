"""What the model tests run on: the facade on `backend="langgraph"` with the model the shell's
`AGENT_CORE_LANGGRAPH_MODEL` names, else `anthropic:claude-haiku-5-5`, and, on Anthropic, a record of the requests at
the Anthropic SDK's HTTP client. `AGENT_CORE_LANGGRAPH_CREDENTIAL` passes through from the shell.

Each test here carries `@pytest.mark.model` (set once, by `pytestmark`, in each file). Keys come from the shell that
starts pytest. The suite adds up what the runs were sent and what was read from cache, and prints that at the end.
"""

import json
import os
from pathlib import Path

import pytest

import agent_core
from agent_core.contracts.events import ModelResponded

MODEL = os.environ.get("AGENT_CORE_LANGGRAPH_MODEL") or "anthropic:claude-haiku-5-5"
ANTHROPIC = MODEL.startswith("anthropic:")   # the wire record reads Anthropic's transport only
INSTANCE = Path(__file__).resolve().parent / "instance"
TOTALS = {"requests": 0, "sent": 0, "cache_read": 0, "cache_written": 0}


def _strip_cache_control(value):
    if isinstance(value, dict):
        return {k: _strip_cache_control(v) for k, v in value.items() if k != "cache_control"}
    if isinstance(value, list):
        return [_strip_cache_control(v) for v in value]
    return value


class Wire:
    """The request bodies the provider's HTTP client was asked to send."""

    def __init__(self):
        self.requests: list[dict] = []

    @staticmethod
    def system_text(body: dict) -> str:
        system = body.get("system") or ""
        return system if isinstance(system, str) else "".join(b.get("text", "") for b in system)

    @staticmethod
    def text_of(content) -> str:
        if isinstance(content, str):
            return content
        return "".join(b.get("text", "") for b in content if b.get("type") == "text")

    @staticmethod
    def tools(body: dict) -> list[tuple[str, str, dict]]:
        return [(t["name"], t.get("description", ""), t["input_schema"]) for t in body.get("tools", [])]

    @staticmethod
    def messages(body: dict) -> list[dict]:
        """The conversation of a request, without the cache markers the backend adds."""
        return _strip_cache_control(body["messages"])


@pytest.fixture
def wire(monkeypatch):
    """The record of Anthropic's requests; `None` on another provider, whose wire has no reader here."""
    if not ANTHROPIC:
        return None
    import anthropic._base_client as base

    # The SDK sends through `httpx2` in this environment, not `httpx`; patch the client class the SDK itself imported.
    http = getattr(base, "httpx2", None) or base.httpx
    record = Wire()
    send = http.AsyncClient.send

    async def recording_send(self, request, **kwargs):
        response = await send(self, request, **kwargs)
        if request.url.path.endswith("/messages") and response.status_code < 400:  # a request the client retried counts once
            record.requests.append(json.loads(request.content))
        return response

    monkeypatch.setattr(http.AsyncClient, "send", recording_send)
    return record


@pytest.fixture
async def harness(monkeypatch, tmp_path):
    """`harness(**options)`: a harness on the model-test instance, on the LangGraph backend and Haiku."""
    monkeypatch.setenv("AGENT_CORE_LANGGRAPH_MODEL", MODEL)
    opened = []

    def make(**options):
        options = {"backend": "langgraph", "runs": tmp_path / "runs", **options}
        opened.append(agent_core.open(INSTANCE / "instance.yaml", **options))
        return opened[-1]

    yield make
    for each in opened:
        for event in each.events.record():
            if isinstance(event, ModelResponded):
                usage = event.response.usage
                TOTALS["requests"] += 1
                TOTALS["sent"] += usage.sent or 0
                TOTALS["cache_read"] += usage.cache_read or 0
                TOTALS["cache_written"] += usage.cache_written or 0
        await each.close()


def pytest_terminal_summary(terminalreporter):
    if TOTALS["requests"]:
        terminalreporter.write_line(
            "model tokens: {requests} requests, {sent} sent, {cache_read} read from cache, {cache_written} written to cache".format(**TOTALS)
        )
