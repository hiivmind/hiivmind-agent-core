"""The function tools of the model-test instance."""

import time

REVISIONS = {"alpha": "r1", "beta": "r2", "gamma": "r3", "delta": "r4", "epsilon": "r5"}


def known_name(name: str) -> bool:
    """Whether the register holds the name."""
    return name in REVISIONS


def lookup_revision(state, name: str | None = None) -> dict:
    """Look up the revision of a name in the register; by default the name this node was given."""
    name = state["name"] if name is None else name
    revision = REVISIONS[name]
    state["revision"] = revision
    return {"name": name, "revision": revision}


def slow_lookup(name: str) -> dict:
    """Look up the revision of a name in the register, slowly: the answer comes after twenty seconds."""
    time.sleep(20)
    return {"name": name, "revision": REVISIONS[name]}
