"""What the provider module's `usage` puts in the record (SCOPE-7). F14 stays `not built`: `models.usage` has no consumer."""

import sys
from pathlib import Path

CONFORMANCE = Path(__file__).resolve().parents[2] / "conformance"
sys.path.insert(0, str(CONFORMANCE))
import script_model  # noqa: E402,F401  (registers the `script` provider)

import agent_core  # noqa: E402

EXIT = [["exit", {"outcome": "done", "outputs": {}}]]
LOOKUP = [["lookup_revision", {"name": "alpha"}]]


async def test_usage_reaches_the_record(tmp_path, monkeypatch):     # SCOPE-7
    import json

    scripts = tmp_path / "scripts"
    scripts.mkdir()
    steps = [
        {"calls": LOOKUP, "usage": {"input_tokens": 100, "input_token_details": {"cache_read": 0, "cache_creation": 40}}},
        {"calls": EXIT, "usage": {"input_tokens": 150, "input_token_details": {"cache_read": 40, "cache_creation": 0}}},
    ]
    (scripts / "lookup.json").write_text(json.dumps(steps))
    monkeypatch.setenv("AGENT_CORE_LANGGRAPH_MODEL", f"script:{scripts}")
    h = agent_core.open(CONFORMANCE / "instance" / "instance.yaml", backend="langgraph", runs=tmp_path / "runs")
    try:
        outcome = await h.nodes.run("lookup", {"name": "alpha"})
    finally:
        await h.close()
    [note] = outcome.notes
    assert note.model_calls == 2
    assert (note.usage.sent, note.usage.cache_read, note.usage.cache_written) == (250, 40, 40)
