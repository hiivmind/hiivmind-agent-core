"""Checks and tools of the sequences fixture. Each reads an environment variable a test sets."""
import json
import os
from pathlib import Path


def _run_dir() -> Path:
    return Path(os.environ["AGENT_CORE_RUN_DIR"])


def ready() -> bool:
    return os.environ.get("SEQ_READY", "1") == "1"


def index_is_v2() -> bool:
    return os.environ.get("SEQ_INDEX_V2", "1") == "1"


def refresh_needed() -> bool:
    return os.environ.get("SEQ_REFRESH_NEEDED", "1") == "1"


def stale_batches() -> list:
    """The batches whose files changed."""
    with (_run_dir() / "stale_batches.calls").open("a") as f:
        f.write("1\n")
    return json.loads(os.environ.get("SEQ_STALE", '["s1", "s2"]'))


def crash_point(node: str) -> str:
    """Record that `node` ran, and in which process; end the process at once where SEQ_CRASH names the node.

    With SEQ_CRASH_AT=n, only the n-th call for that node ends it, counted in the run directory.
    """
    with (_run_dir() / "calls.jsonl").open("a") as f:
        f.write(json.dumps({"node": node, "pid": os.getpid(), "label": os.environ.get("SEQ_LABEL")}) + "\n")
    if os.environ.get("SEQ_CRASH") == node:
        counter = _run_dir() / f"crash_{node}.count"
        count = int(counter.read_text()) + 1 if counter.exists() else 1
        counter.write_text(str(count))
        if count == int(os.environ.get("SEQ_CRASH_AT", count)):
            os._exit(3)
    return "ok"


def log_input(action: str) -> bool:
    """Record the input a node was given; always met."""
    with (_run_dir() / "inputs.jsonl").open("a") as f:
        f.write(json.dumps({"action": action}) + "\n")
    return True
