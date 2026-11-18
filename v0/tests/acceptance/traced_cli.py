"""`agent-core`, with a trace of what each request to the provider carried and what came back, written where the
provider's HTTP client sends it. The acceptance suite runs this file instead of the bare command; the trace is
switched on by the environment variable `AGENT_CORE_WIRE_TRACE`, which names the file the lines are appended to.

Nothing here is the harness's own record: the suite reads what the model was sent and what it answered from the wire.
"""

import json
import os
import sys
import time
from pathlib import Path

TRACE_ENV = "AGENT_CORE_WIRE_TRACE"


def _text(system) -> str:
    if not system:
        return ""
    return system if isinstance(system, str) else "\n".join(b.get("text", "") for b in system)


def _answer(response) -> dict | None:
    """The calls and text of a response that was read in full; None for a streamed one."""
    try:
        blocks = json.loads(response.content).get("content") or []
    except Exception:
        return None
    return {
        "calls": [{"id": b["id"], "name": b["name"], "input": b["input"]} for b in blocks if b.get("type") == "tool_use"],
        "text": "".join(b.get("text", "") for b in blocks if b.get("type") == "text"),
    }


def install(path: Path) -> None:
    import anthropic._base_client as base

    # The SDK sends through `httpx2` in this environment, not `httpx`; patch the client class the SDK itself imported.
    http = getattr(base, "httpx2", None) or base.httpx
    send = http.AsyncClient.send

    async def recording_send(self, request, **kwargs):
        sent = time.time()
        response = await send(self, request, **kwargs)
        if request.url.path.endswith("/messages") and response.status_code < 400:  # a request the client retried counts once
            body = json.loads(request.content)
            offered = body.get("tools") or []
            line = {
                "ts": sent,
                "pid": os.getpid(),
                "model": body.get("model"),
                "system": _text(body.get("system")),
                "tools": [t["name"] for t in offered],
                "params": {t["name"]: sorted((t.get("input_schema") or {}).get("properties") or {}) for t in offered},
                "messages": body["messages"],
                "response": _answer(response),
            }
            with path.open("a") as f:
                f.write(json.dumps(line) + "\n")
        return response

    http.AsyncClient.send = recording_send


if __name__ == "__main__":
    if os.environ.get(TRACE_ENV):
        install(Path(os.environ[TRACE_ENV]))
    from agent_core.core.cli import main

    sys.exit(main())
