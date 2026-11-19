"""Checks made before a node or a sequence starts: a node's inputs, and declared checks (NODE-8a, NODE-11 to NODE-13a)."""

import copy
import dataclasses
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence

from agent_core.contracts.errors import ToolError, ToolServerError
from agent_core.contracts.topology import Check, NodeContract


class CheckError(ValueError):
    """A declared precondition check could not be run. That is an error, not an unmet precondition."""


class StateView(dict):
    """A copy of the state for one call. `written` holds the names written through it."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.written: set[str] = set()

    def __setitem__(self, key, value):
        self.written.add(key)
        super().__setitem__(key, value)

    def update(self, *args, **kwargs):
        for key, value in dict(*args, **kwargs).items():
            self[key] = value

    def setdefault(self, key, default=None):
        if key not in self:
            self[key] = default
        return self[key]

    def __ior__(self, other):
        self.update(other)
        return self


def written(before: Mapping, after: StateView) -> list[tuple[str, object]]:
    """What a function tool wrote: names assigned through `after`, and values changed in place."""
    return [
        (key, value)
        for key, value in after.items()
        if key in after.written or key not in before or before[key] != value
    ]


def unknown_inputs(node: NodeContract, inputs: Mapping) -> str | None:
    """The refusal for the first input the node does not declare, or None."""
    for name in inputs:
        if name not in node.inputs:
            declared = f"its inputs are: {', '.join(node.inputs)}" if node.inputs else "it takes no inputs"
            return f"`{node.name}` has no input `{name}`; {declared}"
    return None


def _met(result: object) -> bool:
    """The shell tool reports an exit code: zero is met. Another tool says "not met" by returning false."""
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except ValueError:
            return True  # a result that is not JSON is not `false`
    return result is not False and (not isinstance(result, dict) or result.get("exit", 0) == 0)


async def unmet_check(
    checks: Sequence[Check],
    facts: Mapping,
    *,
    owner: str,
    call: Callable[[str, dict, dict], Awaitable[object]],
    functions: frozenset[str],
    fill: Callable[[str], str],
) -> tuple[dict | None, dict]:
    """Run declared checks in order; each is a call, `call(name, args, state)`, to a declared tool. `owner` is the node
    or sequence they belong to.

    Returns the first check that is not met, as a dict with its message filled, or None; and what the checks wrote. A
    check by a function tool is given one `StateView` of the facts, shared by the checks, so a later check sees what an
    earlier one wrote (NODE-11). When a check is not met nothing is returned as written. A tool the port does not know
    is the port's `ToolError`, and so a check that cannot be run.
    """
    state = StateView(copy.deepcopy(dict(facts)))
    before = copy.deepcopy(dict(state))
    cannot = f"the precondition check for `{owner}` could not be run"
    for check in checks:
        name = check.tool
        args = {k: fill(v) if isinstance(v, str) else v for k, v in check.args.items()}
        if name in functions:  # a check written in Python is a function tool: true means met
            try:
                met = bool(await call(name, args, state))
            except Exception as e:
                raise CheckError(f"{cannot}: {name} raised {type(e).__name__}: {e}") from None
        else:
            try:
                met = _met(await call(name, args, {}))
            except (ToolError, ToolServerError) as e:
                raise CheckError(f"{cannot}: {e}") from None
        if not met:
            unmet = dataclasses.asdict(check)
            if check.outcome is None:  # the key's presence is what routes an unmet check (v0): absent, not None
                del unmet["outcome"]
            return {**unmet, "message": fill(check.message)}, {}
    return None, dict(written(before, state))
