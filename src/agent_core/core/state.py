"""What the harness holds between a node's steps: session facts and the node that is running (§5.5).

Nothing here belongs to a framework. A store saves what `to_dict` returns.
"""

import copy
from dataclasses import asdict, dataclass, field
from typing import Literal

from agent_core.core.instance import Node


@dataclass
class Slot:
    name: str
    inputs: dict
    values: dict                    # working values, cleared when the node exits (ST-2)
    outputs: dict                   # declared outputs recorded while the node ran; they count on EXIT (JOB-7a)
    rejections: int = 0
    pending_question: str | None = None


@dataclass
class HarnessState:
    session: dict
    node: Slot | None = None
    temporary: Slot | None = None
    menu_waiting: bool = False
    transcript: list = field(default_factory=list)


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


def view(state: HarnessState, slot: Slot | None) -> StateView:
    """Session facts, then working values, then inputs; a later one hides an earlier of the same name (TOOL-12)."""
    seen = dict(state.session)
    if slot is not None:
        seen |= slot.values | slot.inputs
    return StateView(copy.deepcopy(seen))


def target(node: Node, key: str) -> Literal["inputs", "session", "values"]:
    if key in node.inputs:
        return "inputs"
    if key in node.outputs:
        return "session"
    return "values"


def record_value(state: HarnessState, slot: Slot, node: Node, key: str, value: object) -> str:
    where = target(node, key)
    if where == "inputs":
        slot.inputs[key] = value
        slot.pending_question = None
    elif where == "session":
        state.session[key] = value
        slot.outputs[key] = value
    else:
        slot.values[key] = value
    return where


def written(node: Node, before: dict, after: StateView) -> list[tuple[str, object]]:
    """What a function tool wrote: names assigned through `after`, and values changed in place."""
    return [
        (key, value)
        for key, value in after.items()
        if key in after.written or key not in before or before[key] != value
    ]


def close_slot(state: HarnessState, which: Literal["node", "temporary"], outputs: dict) -> None:
    """ST-2: merge the outputs into the session facts and clear the slot; the other slot is untouched."""
    state.session.update(outputs)
    setattr(state, which, None)


def to_dict(state: HarnessState) -> dict:
    return copy.deepcopy(asdict(state))


def from_dict(d: dict) -> HarnessState:
    d = copy.deepcopy(d)
    return HarnessState(
        session=d["session"],
        node=Slot(**d["node"]) if d.get("node") is not None else None,
        temporary=Slot(**d["temporary"]) if d.get("temporary") is not None else None,
        menu_waiting=d.get("menu_waiting", False),
        transcript=d.get("transcript", []),
    )
