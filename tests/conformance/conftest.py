"""What the conformance suite runs on: a driver for each backend that has a model, a record of the requests
at the provider's HTTP client, and a toy controller. The suite is written against `NodeDriver`; the core is not used.
"""

import asyncio
import importlib.util
import json
import uuid

import pytest

from agent_core.contracts import EndRun, ModelResponse, Result, ToolCall, ToolSpec
from agent_core.core.registry import BACKENDS, backend

NO_MODEL = "no backend with a model"

LOOKUP = ToolSpec(
    "lookup",
    "Look up a source's revision by its name.",
    {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
)
EXIT = ToolSpec(
    "exit",
    "Finish the node. Call it when the procedure says the node is done.",
    {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]},
)
REVISIONS = {"alpha": 41, "beta": 7, "gamma": 112, "delta": 3, "epsilon": 20}


def with_model() -> list[str]:
    """Names of the backends whose settings class has a `MODEL` field and whose library is installed."""
    names = []
    for name, (_, package) in BACKENDS.items():
        if package and importlib.util.find_spec(package) is None:
            continue
        _, settings_cls = backend(name)
        if "MODEL" in settings_cls.model_fields:
            names.append(name)
    return names


def pytest_generate_tests(metafunc):
    if "driver" not in metafunc.fixturenames:
        return
    names = with_model()
    if names:
        metafunc.parametrize("driver", names, indirect=True)
    else:
        metafunc.parametrize("driver", [pytest.param(None, marks=pytest.mark.skip(reason=NO_MODEL))], indirect=True)


@pytest.fixture
def driver(request):
    cls, settings_cls = backend(request.param)
    return cls(settings_cls())


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
    import anthropic._base_client as base

    http = getattr(base, "httpx2", None) or base.httpx  # the HTTP library the provider's SDK uses
    record = Wire()
    send = http.AsyncClient.send

    async def recording_send(self, request, **kwargs):
        response = await send(self, request, **kwargs)
        if request.url.path.endswith("/messages") and response.status_code < 400:  # a request the client retried counts once
            record.requests.append(json.loads(request.content))
        return response

    monkeypatch.setattr(http.AsyncClient, "send", recording_send)
    return record


class ToyController:
    """Answers `lookup`, ends the run on `exit`, and records what it is asked, in order."""

    def __init__(self):
        self.events: list[tuple] = []
        self.responses: list[ModelResponse] = []
        self.handled: list[ToolCall] = []
        self.replies: list[str | None] = []  # what `stopped` answers, one for each time it is asked; then None
        self.said: list[str] = []
        self.hold = 0.0  # seconds a `lookup` is held
        self.inside = None  # an async callable run inside a `lookup`

    async def handle(self, call: ToolCall):
        self.events.append(("handle", call))
        self.handled.append(call)
        if call.name == "exit":
            return EndRun()
        if call.name == "lookup":
            if self.hold:
                await asyncio.sleep(self.hold)
            if self.inside is not None:
                await self.inside()
            name = call.args.get("name", "")
            if name in REVISIONS:
                return Result(f"revision {REVISIONS[name]}")
            return Result(f"no source named {name}", error=True)
        return Result(f"no tool {call.name}", error=True)

    async def responded(self, response: ModelResponse) -> None:
        self.events.append(("responded", response))
        self.responses.append(response)

    async def stopped(self, said: str) -> str | None:
        self.events.append(("stopped", said))
        self.said.append(said)
        return self.replies.pop(0) if self.replies else None


@pytest.fixture
def controller():
    return ToyController()


def _notes(count: int) -> str:
    return "\n".join(
        f"- Note {i}: a source is named by a short word, its revision is a whole number, revisions are never negative, "
        f"and a source that cannot be found is reported by the tool and is not an error of the one calling it."
        for i in range(1, count + 1)
    )


@pytest.fixture
def instructions():
    """Instructions for a toy node. Each is unlike any other, so nothing of it is in a cache before it is used."""

    def make(procedure: str, notes: int = 0) -> str:
        text = f"# Engine rules (run {uuid.uuid4().hex})\n\nYou run one node of a workflow. Follow its procedure and do nothing it does not say.\n\n"
        text += f"## Procedure\n\n{procedure}\n"
        if notes:
            text += f"\n## Reference notes\n\n{_notes(notes)}\n"
        return text

    return make


@pytest.fixture
def toy_tools():
    return (LOOKUP, EXIT)


@pytest.fixture
def quiet():
    """A controller for a run that has no tools: any call is a failure."""

    class Quiet:
        async def handle(self, call):
            raise AssertionError("a run with no tools made a call")

        async def responded(self, response):
            pass

        async def stopped(self, said):
            return None

    return Quiet()
