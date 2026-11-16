"""Checks made before a node or a sequence starts: a node's inputs, and declared checks (NODE-8a, NODE-11 to NODE-13a)."""

import copy
import json
from collections.abc import Callable, Mapping, Sequence

from agent_core.contracts.errors import ToolError, ToolServerError
from agent_core.contracts.tools import ToolSource
from agent_core.contracts.values import ToolSpec
from agent_core.core.instance import Node
from agent_core.core.state import StateView, written


class CheckError(ValueError):
    """A declared precondition check could not be run. That is an error, not an unmet precondition."""


def unknown_inputs(node: Node, inputs: Mapping) -> str | None:
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
    checks: Sequence[dict],
    facts: Mapping,
    *,
    owner: str,
    tools: Mapping[str, tuple[ToolSource, ToolSpec]],
    functions: set[str],
    fill: Callable[[str], str],
) -> tuple[dict | None, dict]:
    """Run declared checks in order; each is a call to a declared tool. `owner` is the node or sequence they belong to.

    Returns the first check that is not met, as a copy with its message filled, or None; and what the checks wrote. A
    check by a function tool is given one `StateView` of the facts, shared by the checks, so a later check sees what an
    earlier one wrote (NODE-11). When a check is not met nothing is returned as written.
    """
    state = StateView(copy.deepcopy(dict(facts)))
    before = copy.deepcopy(dict(state))
    cannot = f"the precondition check for `{owner}` could not be run"
    for check in checks:
        name = check["tool"]
        if name not in tools:
            raise CheckError(f"{cannot}: no tool `{name}`")
        source = tools[name][0]
        args = {k: fill(v) if isinstance(v, str) else v for k, v in (check.get("args") or {}).items()}
        if name in functions:  # a check written in Python is a function tool: true means met
            try:
                met = bool(await source.call(name, args, state))
            except Exception as e:
                raise CheckError(f"{cannot}: {name} raised {type(e).__name__}: {e}") from None
        else:
            try:
                met = _met(await source.call(name, args, {}))
            except (ToolError, ToolServerError) as e:
                raise CheckError(f"{cannot}: {e}") from None
        if not met:
            return {**check, "message": fill(check["message"])}, {}
    return None, dict(written(before, state))
