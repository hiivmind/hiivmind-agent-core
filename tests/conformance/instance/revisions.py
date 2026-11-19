"""The function tools of the conformance instance: the revision register and a tool that ends the process once."""

import os
from pathlib import Path

REVISIONS = {"alpha": "r1", "beta": "r2", "gamma": "r3"}


def known_name(name: str) -> bool:
    """Whether the register holds the name."""
    return name in REVISIONS


def lookup_revision(state, name: str | None = None) -> dict:
    """Look up the revision of a name in the register; by default the name this node was given."""
    name = state["name"] if name is None else name
    revision = REVISIONS[name]
    state["revision"] = revision  # an output the node declares: recorded as such
    return {"name": name, "revision": revision}


def crash_once() -> str:
    """End the process, once: while the file `crash-once` exists in the run directory, remove it and exit."""
    marker = Path(os.environ["AGENT_CORE_RUN_DIR"]) / "crash-once"
    if marker.exists():
        marker.unlink()
        raise SystemExit(3)
    return "survived"
