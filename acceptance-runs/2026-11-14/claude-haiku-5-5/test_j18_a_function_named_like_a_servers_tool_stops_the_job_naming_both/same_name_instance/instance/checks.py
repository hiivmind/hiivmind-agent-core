"""Precondition checks written in Python. Each is a function tool (instance.yaml, `tools:`): true means the precondition is met."""


def never_ready(settings, state) -> bool:
    return False


def broken() -> bool:
    raise RuntimeError("the readiness file is unreadable")


def stamp_ready(settings, state) -> bool:
    """A check that is met may leave facts for the node it guards: the harness records them when the node starts."""
    state["stamp"] = f"ready-{settings.CORPUS_NAME}"  # an output the node declares: a fact, and it counts on EXIT
    state["checked_by"] = "the harness"  # another name: a working value of the node
    return True


def stamp_unready(settings, state) -> bool:
    state["stamp"] = "written by a check that was not met"  # the check is not met, so nothing is recorded
    return False
