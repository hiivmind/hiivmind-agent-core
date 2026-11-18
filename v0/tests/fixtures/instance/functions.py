"""Tools this instance declares as plain Python functions (`tools:` in instance.yaml).

Each call is appended to $AGENT_CORE_RUN_DIR/function_calls.jsonl with the process that ran it. That
file is the probes' record of which function tools really ran, and where.
"""
import json
import os
import time
from pathlib import Path


def _record(tool: str, args: dict) -> None:
    line = {"ts": time.time(), "pid": os.getpid(), "tool": tool, "args": args}
    with (Path(os.environ["AGENT_CORE_RUN_DIR"]) / "function_calls.jsonl").open("a") as f:
        f.write(json.dumps(line) + "\n")


def count_words(text: str) -> dict:
    """Count the words in a text."""
    _record("count_words", {"text": text})
    return {"words": len(text.split())}


def read_ledger(name: str, state) -> dict:
    """Read a ledger file of the corpus."""
    _record("read_ledger", {"name": name})
    state["ledger_tried"] = name  # the function raises next, so the harness must not record this
    raise FileNotFoundError(f"no ledger named {name}")


def locate(source: str, settings, state) -> dict:
    """Say where a source of the corpus is kept."""
    _record("locate", {"source": source, "corpus_path": settings.CORPUS_PATH, "state": dict(state)})
    path = f"{settings.CORPUS_PATH}/{source}"
    state["path"] = path  # `path` is an output the node declares: the harness records it as a fact
    state["last_located"] = source  # any other name: a working value of the node that is running
    return {"path": path}
