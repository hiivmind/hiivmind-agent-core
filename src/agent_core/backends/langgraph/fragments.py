"""A declared fragment compiled into a `StateGraph` (architecture §4.3, §4.4a; ORC-5).

One graph node runs each node of the fragment, as `run_node` does. A fan-out is a worker node that `Send` dispatches once
per item, a join node that collects the workers' results in item order, and, for a list computed by a tool, a node of its
own, so that the checkpoint keeps the list (FAN-6, FAN-7). The result is the contract the walk helper gives
(`walk_fragment`): its exit, its declared outputs, and its inner steps.
"""

import asyncio
import operator
from collections.abc import Awaitable, Callable, Mapping
from typing import Annotated, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END as GRAPH_END
from langgraph.graph import START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send

from agent_core.contracts.errors import ProviderRefused, ProviderUnavailable
from agent_core.contracts.topology import END, FanOut, FragmentDef, Link, Step, Target
from agent_core.contracts.unit import Intent, Unit, UnitResult
from agent_core.contracts.walk import RETRY_PAUSE
from agent_core.helpers.walk import SequenceError

NodeRunner = Callable[[str, Mapping, Intent, str], Awaitable[UnitResult]]   # (node, inputs, intent, thread) -> its result
Begun = Callable[[str], Awaitable[bool]]   # whether a thread has a checkpoint


def _merge(current: dict | None, update: dict) -> dict:
    return {**(current or {}), **update}


def _by_item(current: dict | None, update: dict) -> dict:
    """The workers' results, `{fan-out node: {item number: record}}`: a worker adds its own, and `None` clears a node's."""
    merged = {node: dict(items) for node, items in (current or {}).items()}
    for node, items in update.items():
        if items is None:
            merged.pop(node, None)
        else:
            merged.setdefault(node, {}).update(items)
    return merged


class FragmentState(TypedDict, total=False):
    facts: Annotated[dict, _merge]        # what the fragment has found: its inputs and each step's declared outputs
    trail: Annotated[list, operator.add]  # the inner steps, in the order they ended
    results: Annotated[dict, _by_item]    # a fan-out's workers' results, by node and item number
    items: Annotated[dict, _merge]        # the lists tools computed, by the fan-out's node
    outcome: str | None                   # how the last step ended
    ended: dict | None                    # {"end": "stopped"} or {"end": "failed", "reason": ...}


def initial_state(fragment: FragmentDef, inputs: Mapping) -> FragmentState:
    """The fragment's declared inputs found in `inputs`."""
    facts = {name: inputs[name] for name in fragment.inputs if name in inputs}
    return {"facts": facts, "trail": [], "results": {}, "items": {}, "outcome": None, "ended": None}


def fragment_result(fragment: FragmentDef, state: Mapping) -> UnitResult:
    """The fragment's exit is the last step's outcome (SEQ-10); a stop ends it `stopped` (SEQ-7); an outcome its
    transitions have no row for ends it `failed`, with the reason the step gave."""
    steps = tuple(state["trail"])
    facts = state["facts"]
    outputs = {name: facts[name] for name in fragment.outputs if name in facts}
    ended = state["ended"]
    if ended is None:
        return UnitResult(state["outcome"] or "done", outputs, steps=steps)
    if ended["end"] == "stopped":
        return UnitResult("stopped", outputs, steps=steps)
    return UnitResult("failed", outputs, reason=ended["reason"], steps=steps)


def _record(result: UnitResult) -> dict:
    return {"exit": result.exit, "outputs": result.outputs, "reason": result.reason, "detail": result.detail}


def _inner(name: str, record: Mapping) -> dict:
    """An inner step as the fragment's trail keeps it: the name and outcome, the node's own outputs when it failed, and
    the harness's reason and detail when it has them (JOB-9a, JOB-13)."""
    kept = {"name": name, "outcome": record["exit"]}
    if record["exit"] == "failed" and record["outputs"]:
        kept["outputs"] = dict(record["outputs"])
    if record["reason"]:
        kept["reason"] = record["reason"]
    if record["detail"]:
        kept["detail"] = dict(record["detail"])
    return kept


class _Gate:
    """One fan-out's limit on the runs at once (FAN-1), and whether a run of it stopped (SEQ-7)."""

    def __init__(self, limit: int):
        self.limit = limit
        self.semaphore = asyncio.Semaphore(limit)
        self.stopped = False


class _Compiler:
    def __init__(self, fragment: FragmentDef, unit: Unit, run: NodeRunner, begun: Begun):
        self.fragment, self.unit, self.run, self.begun = fragment, unit, run, begun
        self.rows = fragment.transitions
        self.graph = StateGraph(FragmentState)
        self.added: set[str] = set()
        self.fan_outs: dict[str, FanOut] = {}
        self.gates: dict[str, _Gate] = {}

    def compile(self, checkpointer: BaseCheckpointSaver | None) -> CompiledStateGraph:
        self._reach(self.fragment.start)
        self.graph.add_conditional_edges(START, lambda state: self._enter(self.fragment.start, state))
        return self.graph.compile(checkpointer=checkpointer)

    # --- the graph's nodes -------------------------------------------------------------------------------------------

    def _reach(self, target: Target) -> None:
        """Add the graph nodes `target` needs, and those of the targets its own transitions lead to."""
        if target == END:
            return
        if isinstance(target, Link):
            raise ValueError(f"fragment `{self.fragment.name}`: a link to a sequence does not return, so a fragment holds none")
        if isinstance(target, FanOut):
            name, new = target.node, self._add_fan_out(target)
        else:
            name, new = target.name, self._add_step(target)
        if new:
            for row_target in self.rows.get(name, {}).values():
                self._reach(row_target)

    def _add_step(self, step: Step) -> bool:
        graph_id = self._id(step)
        if graph_id in self.added:
            return False
        self.added.add(graph_id)
        self.graph.add_node(graph_id, self._step(step.name, step.mapping, graph_id))
        self.graph.add_conditional_edges(graph_id, self._leave(step.name))
        return True

    def _add_fan_out(self, spec: FanOut) -> bool:
        node = spec.node
        if node in self.fan_outs:
            if self.fan_outs[node] != spec:
                raise ValueError(f"fragment `{self.fragment.name}` fans out `{node}` in two ways")
            return False
        self.fan_outs[node] = spec
        self.gates[node] = _Gate(spec.max_concurrency)
        self.graph.add_node(f"{node}[item]", self._worker(spec))
        self.graph.add_node(f"{node}[join]", self._join(spec))
        self.graph.add_edge(f"{node}[item]", f"{node}[join]")
        self.graph.add_conditional_edges(f"{node}[join]", self._leave(node))
        if not isinstance(spec.over, str):
            self.graph.add_node(f"{node}[list]", self._list(spec))
            self.graph.add_conditional_edges(f"{node}[list]", lambda state: self._send(spec, state["items"][node], state, spec.over.tool))
        return True

    @staticmethod
    def _id(step: Step) -> str:
        """The graph node of a step: a node entered with a mapping of its inputs is a node of its own."""
        if not step.mapping:
            return step.name
        return f"{step.name}({', '.join(f'{k}={v}' for k, v in sorted(step.mapping.items()))})"

    def _inputs(self, node: str, facts: Mapping, mapping: Mapping[str, str]) -> dict:
        """Each declared input of the node that has a fact, by its own name or the name the mapping gives (SEQ-5)."""
        return {n: facts[mapping.get(n, n)] for n in self.unit.topology.nodes[node].inputs if mapping.get(n, n) in facts}

    def _declared(self, node: str, outputs: Mapping) -> dict:
        declared = self.unit.topology.nodes[node].outputs
        return {k: v for k, v in outputs.items() if k in declared}   # SEQ-6

    def _ended(self, source: str, outcome: str) -> dict | None:
        if outcome == "stopped":   # SEQ-7
            return {"end": "stopped"}
        if self.rows.get(source, {}).get(outcome) is None:   # SEQ-10
            return {"end": "failed", "reason": f"`{source}` exited `{outcome}` and the sequence has no transition for it"}
        return None

    def _step(self, name: str, mapping: Mapping[str, str], graph_id: str):
        async def step(state: FragmentState) -> dict:
            result = await self.run(name, self._inputs(name, state["facts"], mapping), "start", f"{self.unit.thread}/{graph_id}/0")
            record = _record(result)
            return {
                "facts": self._declared(name, result.outputs), "trail": [_inner(name, record)], "outcome": result.exit,
                "ended": self._ended(name, result.exit),
            }

        return step

    def _list(self, spec: FanOut):
        async def listed(state: FragmentState) -> dict:   # FAN-5, FAN-6: a step of its own, kept by the checkpoint
            items = await self.unit.call_tool(spec.over.tool, dict(spec.over.args))
            return {"items": {spec.node: items}, "trail": [{"name": f"{spec.node}[list]", "outcome": "done"}]}

        return listed

    def _worker(self, spec: FanOut):
        node, gate = spec.node, self.gates[spec.node]

        async def worker(payload: dict) -> dict:
            n = payload["n"]
            async with gate.semaphore:   # the limit wraps the run, not the dispatch (FAN-1)
                if gate.stopped:   # a run stopped: runs not yet started do not start
                    return {"results": {node: {n: {"ran": False}}}}
                record = _record(await self._attempt(node, payload["inputs"], f"{self.unit.thread}/{node}/{n}"))
                gate.stopped = gate.stopped or record["exit"] == "stopped"
            return {"results": {node: {n: {"ran": True, "item": payload["item"], **record}}}}

        return worker

    async def _attempt(self, node: str, inputs: Mapping, base: str) -> UnitResult:
        """One item's run. A run that raises is a failed item. A run the provider found unavailable is run once more,
        fresh, after `RETRY_PAUSE` seconds (RTY-2, RTY-3); one the provider refused for good is not (MOD-4, MOD-5).

        The second run is on its own thread. A second run that has a checkpoint was in flight when the process died: it is
        continued, and the first run is not entered again (§4.4a)."""
        second = f"{base}/2"
        if await self.begun(second):
            intent = "continue"
        else:
            try:
                return await self.run(node, inputs, "start", f"{base}/1")
            except ProviderRefused as e:
                return UnitResult("failed", {"reason": str(e)})
            except ProviderUnavailable:
                pass
            except Exception as e:
                return UnitResult("failed", {"reason": f"{type(e).__name__}: {e}"})
            await asyncio.sleep(RETRY_PAUSE)
            intent = "fresh"
        try:
            return await self.run(node, inputs, intent, second)
        except ProviderRefused as e:
            return UnitResult("failed", {"reason": f"{e} (run twice)"})   # RTY-5: any error of the second run
        except Exception as e:
            return UnitResult("failed", {"reason": f"{type(e).__name__}: {e} (run twice)"})

    def _join(self, spec: FanOut):
        node, into = spec.node, spec.into

        async def join(state: FragmentState) -> dict:   # the results in item order (FAN-3)
            records = state["results"].get(node, {})
            done, failures, trail = [], [], []
            stopped = False
            for n in sorted(records, key=int):
                record = records[n]
                if not record["ran"]:
                    continue
                trail.append(_inner(f"{node}[{n}]", record))
                if record["exit"] == "done":
                    done.append(self._declared(node, record["outputs"]))
                elif record["exit"] == "stopped":
                    stopped = True
                else:
                    failures.append({"item": record["item"], "outcome": record["exit"], "reason": record["outputs"].get("reason", record["reason"])})
            outcome = "stopped" if stopped else "done" if done or not records else "failed"   # FAN-4
            return {
                "facts": {into: done, f"{into}_failures": failures}, "trail": [*trail, {"name": node, "outcome": outcome}],
                "outcome": outcome, "results": {node: None}, "ended": self._ended(node, outcome),
            }

        return join

    # --- the edges ---------------------------------------------------------------------------------------------------

    def _leave(self, source: str):
        """The edge out of the step or the fan-out `source`: where its outcome leads."""

        def route(state: FragmentState):
            if state["ended"] is not None:
                return GRAPH_END
            return self._enter(self.rows[source][state["outcome"]], state)

        return route

    def _enter(self, target: Target, state: FragmentState):
        if target == END:
            return GRAPH_END
        if isinstance(target, FanOut):
            if not isinstance(target.over, str):
                return f"{target.node}[list]"
            return self._send(target, state["facts"].get(target.over), state, target.over)
        return self._id(target)

    def _send(self, spec: FanOut, items: object, state: FragmentState, named: str):
        """One `Send` per item, each with the inputs its run is given (FAN-1); with no item, the join at once (FAN-4)."""
        if not isinstance(items, list):
            raise SequenceError(f"the fan-out over `{named}` needs a list; it got {type(items).__name__}")
        gate = self.gates[spec.node]
        gate.stopped = False
        sends = [
            Send(f"{spec.node}[item]", {"n": n, "item": item, "inputs": self._inputs(spec.node, {**state["facts"], spec.as_: item}, {})})
            for n, item in enumerate(items, 1)
        ]
        return sends or f"{spec.node}[join]"


def compile_fragment(
    fragment: FragmentDef, unit: Unit, node_runner: NodeRunner, begun: Begun, checkpointer: BaseCheckpointSaver | None = None
) -> CompiledStateGraph:
    """The fragment as a graph. `node_runner(node, inputs, intent, thread)` runs one node of it as a unit; a run it
    raises `ProviderUnavailable` for is run once more, with intent `fresh` and a thread of its own (RTY-2); `begun(thread)`
    says whether that thread already has a checkpoint, and then the run is continued (`continue`)."""
    return _Compiler(fragment, unit, node_runner, begun).compile(checkpointer)
