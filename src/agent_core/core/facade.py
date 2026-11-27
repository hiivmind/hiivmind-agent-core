"""`agent_core.open` and the harness it returns: the namespaces of the facade, over the core (FAC-1 to FAC-5).

The harness implements `contracts.facade.Harness`. It loads the instance, its settings and the default backend when it
is opened, so that a run that cannot start is found now. A run starts by resolving what it is made of: its settings, the
servers it holds one connection to for its length (TOOL-15), given the instance and the run directory in their
environment (RP-1), the declared-tool set (the instance's functions and the client's), and each provider looked up by
name. It closes its servers when it ends, whether or not it raised. It changes nothing of the process's environment.
"""

from __future__ import annotations

import asyncio
import copy
import dataclasses
import json
import os
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path

from pydantic import ValidationError

from agent_core.contracts.backend import Backend
from agent_core.contracts.context import HandoverRequest
from agent_core.contracts.errors import FeatureNotSupported, RunCannotStart, ToolError, ToolServerError
from agent_core.contracts.events import Event, NodeStarted
from agent_core.contracts.facade import Events, Extensions, Nodes, SequenceResult, Sequences, SessionResult, Sessions, Tools
from agent_core.contracts.matrix import Feature
from agent_core.contracts.person import Person, Question
from agent_core.contracts.policy import NodeState, Policy
from agent_core.contracts.resources import ResourceSource
from agent_core.contracts.topology import Check, FragmentDef, NodeContract
from agent_core.contracts.unit import DeclaredTools, Intent, Unit, UnitResult
from agent_core.contracts.values import FAILED, HarnessReason, Message, Outcome
from agent_core.contracts.walk import WalkResult
from agent_core.core.brief import make_brief, offer
from agent_core.core.checks import unknown_inputs, unmet_check
from agent_core.core.declared import resolve
from agent_core.core.events import EventHub
from agent_core.core.functions import FunctionTool, describe, import_declared
from agent_core.core.instance import Instance, InstanceError, load_instance
from agent_core.core.macro import Macro
from agent_core.core.policy import NodePolicy, QuietPolicy
from agent_core.core.record import build, failure, masked, new_run_id, notes, now
from agent_core.core.registry import BackendNotInstalled, UnknownBackend, UnknownProvider
from agent_core.core.registry import backend as registered_backend
from agent_core.core.registry import provider as registered_provider
from agent_core.core.routing import unknown_name
from agent_core.core.session import Session, SessionPort, WaitingServers, check_topology, new_state
from agent_core.core.settings import SettingsError, load_settings
from agent_core.core.templates import TemplateError, render

KINDS = ("backend", "context", "person", "resources", "journal", "store")
OPENING = "Run the node."
SUMMARY = "@summary"
RUN_ID = re.compile(r"(.+)-\d{8}T\d{6}Z-[0-9a-f]{6}")


_new_id = new_run_id   # `rerun`'s keyword `new_run_id` hides the function inside it


async def _cannot_summarise(system: str, text: str) -> str:
    raise RuntimeError("a job's node is handed nothing, so it has no summariser")


class _Asking:
    """The person, as one node run sees them: a question is put only when no other question is waiting for its answer
    (JOB-6)."""

    def __init__(self, person: Person, lock: asyncio.Lock):
        self._person, self._lock = person, lock

    async def tell(self, text: str) -> None:
        await self._person.tell(text)

    async def ask(self, question: Question) -> str | None:
        async with self._lock:
            return await self._person.ask(question)

    async def hear(self) -> str | None:
        async with self._lock:
            return await self._person.hear()


class _Recorded:
    """A backend as one run uses it: a failed node run, and a tool server that could not be reached, go into the run's
    record (JOB-9a, TOOL-11e)."""

    def __init__(self, backend: Backend, run: _Run):
        self._backend, self._run = backend, run

    async def run_node(self, unit: Unit) -> UnitResult:
        return await self._record(unit, self._backend.run_node)

    async def run_fragment(self, unit: Unit) -> UnitResult:
        return await self._record(unit, self._backend.run_fragment)

    async def _record(self, unit: Unit, call: Callable[[Unit], Awaitable[UnitResult]]) -> UnitResult:
        try:
            result = await call(unit)
        except ToolServerError as e:
            self._run.failures.append({"node": unit.name, "error": f"{type(e).__name__}: {e}"})
            raise
        for step in result.steps:   # a failed inner step is a failure of the run, whether or not the fragment recovered
            if step["outcome"] == FAILED:
                inner = UnitResult(FAILED, step.get("outputs", {}), step.get("reason"), step.get("detail", {}))
                self._run.failures.append(failure(f"{unit.name}/{step['name']}", inner))
        if result.exit == FAILED:
            self._run.failures.append(failure(unit.name, result))
        return result


class _Run:
    """What one run shares: the declared-tool set and the providers resolved when it started, and what it keeps for its
    record. Its methods are the ports the walk and the units use: `start` is the `NodeStart` of every unit of the run."""

    def __init__(
        self,
        harness: Harness,
        declared: DeclaredTools,
        functions: Mapping[str, FunctionTool],
        settings: object | None,
        resources: ResourceSource,
        person: Person,
        run_dir: Path | None,
        backend_name: str,
        session: SessionPort | None = None,
    ):
        self._h, self.declared, self.functions, self.settings = harness, declared, functions, settings
        self.resources, self.person, self.run_dir = resources, person, run_dir
        self.backend_name, self.session = backend_name, session
        self.labels: list[str] = []
        self.summaries = 0
        self.failures: list[dict] = []

    async def end(self) -> None:
        """Close the run's servers."""
        await self.declared.servers.close()

    async def port(self, name: str, args: dict, state: dict) -> object:
        """A declared tool, called with `state` as a function is given it. A tool that is not declared is a `ToolError`."""
        if name in self.declared.functions:
            tool = self.functions[name]
            given = {"settings": self.settings, "state": state}
            return tool.fn(**args, **{n: given[n] for n in tool.filled})
        if name in self.declared.specs:
            return await self.declared.servers.call(name, args, state)
        raise ToolError(f"no tool `{name}`")

    async def call(self, name: str, args: dict) -> object:
        """A declared tool, called by the harness. A function's own value comes back; a server's text comes back parsed as
        JSON where it parses (JOB-2). A function is given no state."""
        if name not in self.declared.specs:
            raise ValueError(f"no tool `{name}`; the tools are: {', '.join(self.declared.specs)}")
        value = await self.port(name, args, {})
        if name in self.declared.functions or not isinstance(value, str):
            return value
        try:
            return json.loads(value)
        except ValueError:
            return value

    async def check(self, checks: Sequence[Check], facts: dict, owner: str) -> tuple[dict | None, dict]:
        """A sequence's checks, against its facts: `input` placeholders in their args are the facts (§4.2)."""

        def fill(text: str) -> str:
            return render(
                text, file=f"sequence {owner}", settings=self.settings, inputs=facts, session={}, values={},
                resources=self.resources,
            )

        return await unmet_check(checks, facts, owner=owner, call=self.port, functions=self.declared.functions, fill=fill)

    def unit(self, name: str, inputs: Mapping, intent: Intent, thread: str, fragment: FragmentDef | None = None) -> Unit:
        h = self._h
        return Unit(
            name, inputs, intent, thread, self.start, self.declared, h.hub, h.instance.topology, self.call, fragment, self.run_dir
        )

    async def summarise(self, system: str, text: str) -> str:
        """What the model says to `text` under the instructions `system`, in a unit with no tools on the run's backend: a
        run of its own, with a label and a note, and told to nobody (design §3.7, SCOPE-7)."""
        h = self._h
        self.summaries += 1
        label = f"{SUMMARY}#{self.summaries}"
        self.labels.append(label)
        policy = QuietPolicy(label=label, node=SUMMARY, instructions=system, opening=text, events=h.hub)
        h.hub.emit(NodeStarted(label, SUMMARY, (("summary instructions", len(system)),), ()))

        async def start(node: str, inputs: Mapping, thread: str) -> Policy:
            return policy

        unit = Unit(SUMMARY, {}, "start", f"{SUMMARY}/{self.summaries}", start, self.declared, h.hub, h.instance.topology, self.call)
        result = await h.recorded(self.backend_name, self).run_node(unit)
        return result.outputs.get("summary", "")

    async def check_node(self, node: str, inputs: Mapping, facts: Mapping) -> tuple[dict | None, dict]:
        """The node's declared checks (NODE-11 to NODE-13), against the session facts and its inputs: the unmet check (its
        `message`, and its `outcome` if it has one) or None, and what the checks wrote. A placeholder that cannot be filled
        is a `TemplateError`."""
        found = self._h.instance.nodes[node]
        inputs, facts = dict(inputs), dict(facts)

        def fill(text: str) -> str:
            return render(
                text, file=found.file, settings=self.settings, inputs=inputs, session=facts, values={}, resources=self.resources,
            )

        return await unmet_check(
            found.preconditions, {**facts, **inputs}, owner=node, call=self.port, functions=self.declared.functions, fill=fill,
        )

    async def start(self, node: str, inputs: Mapping, thread: str) -> Policy | UnitResult:
        """The node start (NODE-11 to NODE-13a): the declared checks, the brief and the hand-over; a `Policy`, or the result of
        a node that does not start. `thread` is the unit's checkpoint thread.

        In a session (design §3.4) the node starts from the session facts, with its own context strategy and the session's
        person, and its brief is made once: a unit continued on its thread is given the brief its unit entry keeps
        (SS-14). Checks the routing run or the menu already made are not made again."""
        h, session = self._h, self.session
        found = h.instance.nodes[node]
        contract = found.contract
        h.started += 1
        number = h.started   # this run's own: another run may start while this one awaits below
        label = f"{node}#{number}"
        self.labels.append(label)
        for tool in found.allowed_tools:  # a misdeclared node fails before any tool is called
            if tool not in self.declared.specs:
                raise ValueError(f"`{node}` declares the tool `{tool}`, which no tool source offers")
        entry = session.unit(thread) if session is not None else None
        facts = copy.deepcopy(session.facts) if session is not None else {}
        state = NodeState(inputs=dict(inputs), values={}, outputs={}, session=facts, rejections=0, ending=None)
        try:
            if entry is not None and "checked" in entry and "instructions" not in entry:
                writes = entry["checked"]   # the routing run or the menu made the checks (design §3.3)
            else:
                unmet, writes = await self.check_node(node, state["inputs"], state["session"])
                if unmet is not None and "outcome" in unmet:  # NODE-13a: the check's outcome, and no model is called
                    return UnitResult(unmet["outcome"], {}, detail={"message": unmet["message"]})
                if unmet is not None:  # NODE-13
                    return UnitResult(FAILED, {}, reason=HarnessReason.PRECONDITION_UNMET, detail={"message": unmet["message"]})
            for key, value in writes.items():  # what a met check wrote counts as recorded when the node starts (NODE-11)
                _record(state, contract, key, value)
            offered = offer(found, self.declared.specs)
            if entry is not None and "instructions" in entry:   # a continued unit keeps its first brief (SS-14)
                instructions, parts = entry["instructions"], tuple(tuple(p) for p in entry.get("parts", ()))
                handover = tuple(Message(**m) for m in entry["handover"])
            else:
                strategy = h.lookup("context", found.context if session is not None else "none")()   # a job's node gets `none`
                handover = tuple(await strategy.build(HandoverRequest(
                    transcript=tuple(session.transcript) if session is not None else (), facts=state["session"], node=node,
                    inputs=state["inputs"], contract=contract,
                    summarise=self.summarise if session is not None else _cannot_summarise,
                )))
                instructions, offered, parts = make_brief(
                    h.instance, found, inputs=state["inputs"], session=state["session"], values=state["values"],
                    settings=self.settings, resources=self.resources, tools=self.declared.specs, session_mode=session is not None,
                )
        except TemplateError as e:  # TPL-2b, TPL-6b
            return UnitResult(FAILED, {}, reason=HarnessReason.UNKNOWN_PLACEHOLDER, detail={"detail": str(e)})
        if session is not None:
            session.save_unit(thread, {
                **(entry or {}), "node": node, "inputs": dict(inputs), "backend": self.backend_name,
                "instructions": instructions, "handover": [dataclasses.asdict(m) for m in handover], "parts": [list(p) for p in parts],
            })
        h.hub.emit(NodeStarted(label, node, parts, tuple(spec.name for spec in offered)))
        return NodePolicy(
            found, number=number, instructions=instructions, tools=offered, handover=handover, opening=OPENING,
            functions=self.functions, servers=self.declared.servers,
            person=_Asking(session.person if session is not None else self.person, h.person_lock), resources=self.resources,
            settings=self.settings, events=h.hub, start=state, session=session, thread=thread,
        )


async def _stopping(run: Awaitable[WalkResult], stopped: asyncio.Future) -> WalkResult:
    """Await a sequence run, or what stopped its walk, whichever comes first (SS-16). A resumed walk runs in the journal's
    task while `run` waits for its result: when the walk was stopped, the wait is cancelled and awaited, and what stopped
    the walk is raised."""
    task = asyncio.ensure_future(run)
    try:
        await asyncio.wait({task, stopped}, return_when=asyncio.FIRST_COMPLETED)
    except BaseException:
        task.cancel()
        await asyncio.wait({task})
        raise
    if not task.done():
        task.cancel()
        await asyncio.wait({task})
        raise stopped.result()
    return task.result()


def _record(state: NodeState, contract: NodeContract, key: str, value: object) -> None:
    """Record a value a check wrote where it belongs: an input, a declared output (also a session fact), or a value."""
    if key in contract.inputs:
        state["inputs"][key] = value
    elif key in contract.outputs:
        state["outputs"][key] = state["session"][key] = value
    else:
        state["values"][key] = value


class _Nodes:
    def __init__(self, harness: Harness):
        self._h = harness

    async def run(self, node: str, inputs: Mapping | None = None, *, backend: str | None = None) -> Outcome:
        h = self._h
        found = h.instance.nodes.get(node)
        if found is None:
            raise ValueError(f"no node `{node}`; the nodes are: {', '.join(h.instance.nodes)}")
        inputs = dict(inputs or {})
        if (refusal := unknown_inputs(found.contract, inputs)) is not None:  # NODE-8a: before anything else
            raise ValueError(refusal)
        chosen = h.backend(backend)  # REG-2, INST-1a, INST-1b: before any tool is called
        run = await h.begin(None, chosen)
        try:
            result = await _Recorded(chosen, run).run_node(run.unit(node, inputs, "start", ""))
        finally:
            await run.end()
        return Outcome(result.exit, result.outputs, result.reason, result.detail, notes(h.hub.record(), run.labels))


class _Sequences:
    def __init__(self, harness: Harness):
        self._h = harness

    def _known(self, name: str) -> None:
        sequences = self._h.instance.topology.sequences
        if name not in sequences:
            raise RunCannotStart(f"no sequence `{name}`; the sequences are: {', '.join(sorted(sequences)) or 'none'}")

    async def run(self, name: str, inputs: Mapping | None = None, *, run_id: str | None = None) -> SequenceResult:
        self._known(name)
        run_id, facts = run_id or new_run_id(name), dict(inputs or {})
        return await self._h.sequence(run_id, lambda macro: macro.start(run_id, name, facts))

    async def resume(self, run_id: str, *, name: str | None = None, run_dir: Path | None = None) -> SequenceResult:
        """`name`, when given, must be a sequence of the topology; `run_dir` is where the run's files go (default `runs/<run_id>`)."""
        if name is not None:
            self._known(name)
        return await self._h.sequence(run_id, lambda macro: macro.resume(run_id), run_dir)

    async def rerun(
        self, run_id: str, from_step: int, *, new_run_id: str | None = None, name: str | None = None, run_dir: Path | None = None
    ) -> SequenceResult:
        if name is not None:
            self._known(name)
        match = RUN_ID.fullmatch(run_id)
        new = new_run_id or _new_id(match.group(1) if match else run_id)
        return await self._h.sequence(new, lambda macro: macro.rerun(new, run_id, from_step), run_dir)


class _Sessions:
    """Sessions at the terminal (SS-1): started, or resumed by their id, with the harness's person."""

    def __init__(self, harness: Harness):
        self._h = harness

    def _store(self):
        return self._h.lookup("store", "file")(self._h.runs)

    async def start(self, name: str | None = None, *, session_id: str | None = None) -> SessionResult:
        h = self._h
        topology = h.instance.topology
        if name is not None and name not in topology.nodes and name not in topology.sequences:
            raise RunCannotStart(unknown_name(topology, name))   # GW-4c
        check_topology(h.instance)   # SS-12
        session_id, store, state = session_id or new_run_id("session"), self._store(), new_state()
        store.save(session_id, state)
        return await Session(h, session_id, state, store, h.person()).run(name)

    async def resume(self, session_id: str) -> SessionResult:
        h = self._h
        check_topology(h.instance)
        store = self._store()
        state = store.load(session_id)
        if state is None:
            raise RunCannotStart(f"no session {session_id}")   # E9
        if state["status"] == "ended":
            raise RunCannotStart(f"session {session_id} has ended")   # E9
        return await Session(h, session_id, state, store, h.person()).resume()


class _Tools:
    def __init__(self, harness: Harness):
        self._h = harness

    def register(self, fn: Callable, name: str | None = None) -> None:
        self.add(describe(fn, name))

    def add(self, tool: FunctionTool) -> None:
        self._h.functions[tool.name] = tool

    def register_server(self, name: str, spec: dict) -> None:
        self._h.servers[name] = spec  # connected when the next run starts


class _Events:
    def __init__(self, harness: Harness):
        self._h = harness

    def record(self) -> tuple[Event, ...]:
        self._h.require(Feature.F15)
        return self._h.hub.record()


class _Extensions:
    def __init__(self, harness: Harness):
        self._h = harness

    def register(self, kind: str, name: str, provider: object) -> None:
        """Register `provider` as `name` of `kind`. A `person`, `context`, `resources` or `journal` is looked up when a run
        starts (or a node starts), so the next one finds it; it is what the registry holds for that kind: the class or
        function the core calls to make one. A `backend` is a pair, (the backend class, its settings class), and takes
        effect for backends this harness has not made yet: one already made is kept."""
        if kind not in KINDS:
            raise ValueError(f"no extension kind `{kind}`; the kinds are: {', '.join(KINDS)}")
        self._h.held[kind][name] = provider


class Harness:
    """The runtime object `agent_core.open` returns (FAC-1)."""

    nodes: Nodes
    sequences: Sequences
    tools: Tools
    events: Events
    extensions: Extensions

    def __init__(
        self,
        instance_yaml: Path,
        *,
        backend: str | None,
        settings: Sequence[str | Path],
        params: Mapping[str, str] | None,
        person: Person | str | None,
        runs: Path | None,
    ):
        self.root = instance_yaml.resolve().parent
        self.held: dict[str, dict[str, object]] = {kind: {} for kind in KINDS}   # what a client registered
        self.instance: Instance = load_instance(instance_yaml, self.lookup("resources", "folder")(self.root))
        self.settings_files, self._params = [str(f) for f in settings], dict(params or {})
        self.params = masked(self._params, load_settings(self.instance, [Path(f) for f in settings], params))  # now: a bad one stops `open`
        self.backend_name = backend or self.instance.backend
        self.attended = person is not None and person != "nobody"
        self.runs = (Path(runs) if runs is not None else self.root / "runs").resolve()
        self.hub = EventHub()
        self.person_lock = asyncio.Lock()
        self.started = 0
        self.functions: dict[str, FunctionTool] = {}
        self.servers: dict[str, dict] = {}
        self._person = person if person is not None else "nobody"
        self._backends: dict[str, Backend] = {}
        self._closed = False
        self.nodes, self.sequences, self.tools = _Nodes(self), _Sequences(self), _Tools(self)
        self._sessions = _Sessions(self)
        self.events, self.extensions = _Events(self), _Extensions(self)
        if isinstance(self._person, str):
            self.lookup("person", self._person)  # a name the registry does not know stops `open`
        self.backend(None)  # the default backend is made now: its own missing settings stop the run before it starts
        for tool in import_declared(self.root, self.instance.functions):
            self.tools.add(tool)
        for name, spec in self.instance.servers.items():
            self.tools.register_server(name, spec)

    # --- what a run is made of -------------------------------------------------------------------------------

    def lookup(self, kind: str, name: str) -> object:
        """The provider `name` of `kind`: a client's own, else the registry's."""
        try:
            return registered_provider(kind, name, self.held[kind])
        except UnknownProvider as e:
            raise RunCannotStart(str(e)) from e

    def backend(self, name: str | None) -> Backend:
        """The backend `name`, made once for the harness; None is the default (REG-2)."""
        name = name or self.backend_name
        if name not in self._backends:
            try:
                cls, settings = registered_backend(name, self.held["backend"])
                self._backends[name] = cls(settings())  # the backend's settings read their own environment (REG-5)
            except (UnknownBackend, BackendNotInstalled) as e:
                raise RunCannotStart(str(e)) from e
            except ValidationError as e:
                fields = dict.fromkeys(".".join(str(p) for p in error["loc"]) or "(settings)" for error in e.errors())
                raise RunCannotStart(f"backend `{name}`: settings: missing or invalid: {', '.join(fields)}") from None
        return self._backends[name]

    def require(self, feature: Feature) -> None:
        """Refuse the call to a feature the default backend declares `divergent` or `not built` (FAC-5)."""
        entry = self.backend(None).features()[feature]
        if entry.state in ("divergent", "not built"):
            raise FeatureNotSupported(feature, self.backend_name, entry)

    async def begin(self, run_dir: Path | None, backend: Backend | None = None, session: SessionPort | None = None) -> _Run:
        """Start a run (`run_dir` is None outside a sequence): its settings, its servers (TOOL-15, made by `backend`, the
        default one when None, given the instance and the run directory in their environment, RP-1), and the
        declared-tool set (TOOL-16). With a `session`, its node runs are session node runs (design §3.4). The caller calls
        `end` on the run."""
        try:
            settings = load_settings(self.instance, [Path(f) for f in self.settings_files], self._params)
        except SettingsError as e:
            raise RunCannotStart(str(e)) from e
        self.runs.mkdir(parents=True, exist_ok=True)
        if run_dir is not None:
            run_dir.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "AGENT_CORE_INSTANCE": str(self.root), "AGENT_CORE_RUN_DIR": str(run_dir or self.runs)}
        servers = None
        try:
            person = self.person()
            resources = self.lookup("resources", "folder")(self.root)
            chosen = backend or self.backend(None)
            servers = chosen.servers(dict(self.servers), self.root, env)
            if session is not None:   # a server that cannot be reached waits for the person (TOOL-11f)
                servers = WaitingServers(servers, session.person)
            functions = dict(self.functions)
            declared = await resolve(functions, servers, {name: name for name in self.servers})
        except BaseException:
            if servers is not None:
                await servers.close()
            raise
        name = next((n for n, made in self._backends.items() if made is chosen), self.backend_name)
        return _Run(self, declared, functions, settings, resources, person, run_dir, name, session)

    async def sequence(
        self,
        run_id: str,
        go: Callable[[Macro], Awaitable[WalkResult]],
        run_dir: Path | None = None,
        session: SessionPort | None = None,
        backend: str | None = None,
    ) -> SequenceResult:
        """Run a sequence as one journalled run under `run_id`, and keep its record (§4.6, §4.7). A run that raises ends
        `failed`: the record says why, and what the walk had reached (JOB-17, RESUME-2).

        `backend` runs every unit of the sequence instead of the default one: a sequence resumed in a session runs on the
        backend it started with (ST-4). With a `session`, its node runs are session node runs (design §3.10), and a person
        who has gone stops the run unrecorded: `SessionWaits` is raised once the walk has unwound, whether the walk runs in
        this task or, resumed, in the journal's (SS-16)."""
        start = now()
        run_dir = (run_dir or self.runs / run_id).resolve()
        run = await self.begin(run_dir, session=session)
        try:
            journal = self.lookup("journal", "dbos")(self.runs / "journal.sqlite", self.instance.name, run_id)
            macro = Macro(
                self.instance.topology, backends=lambda name: _Recorded(self.backend(name), run),
                default_backend=backend or self.backend_name, make_unit=run.unit, journal=journal, call_tool=run.call,
                check=run.check,
            )
            result = error = None
            try:   # the journal is closed whatever the run raises, cancellation and exits included
                try:
                    result = await (_stopping(go(macro), macro.stopped) if session is not None else go(macro))
                except Exception as e:  # the run raised, or the journal refused it (an unknown id)
                    error = f"{type(e).__name__}: {e}"
                try:
                    sequence = (result or {}).get("sequence") or macro.sequence or await journal.sequence(run_id)
                except Exception:   # a journal that cannot say leaves the record without the name
                    sequence = None
            finally:
                await journal.close()
        finally:
            await run.end()
        record = build(
            params=self.params, settings_files=self.settings_files, backend=self.backend_name, attended=self.attended,
            start=start, end=now(), failures=run.failures, events=self.hub.record(), labels=run.labels, run_id=run_id,
            sequence=sequence, result=result, error=error, progress=macro.progress,
        )
        # a result the journal stored before outputs were kept has none
        outputs = dict(result.get("outputs", {}) if result is not None else macro.progress.get("outputs", {}))
        return SequenceResult(
            record.end_state, record.facts or {}, record.steps, run_id, record.summary, record, run_dir, outputs
        )

    # --- the facade -------------------------------------------------------------------------------------------

    @property
    def sessions(self) -> Sessions:
        """Refused where the default backend declares session persistence or routing `divergent` or `not built` (FAC-5)."""
        self.require(Feature.F6)
        self.require(Feature.F17)
        return self._sessions

    def person(self) -> Person:
        """The person given at `open`: a `Person`, or one made from the registry by its name."""
        return self._person if not isinstance(self._person, str) else self.lookup("person", self._person)()

    def recorded(self, name: str | None, run: _Run) -> _Recorded:
        """The backend `name` (None: the default) as `run` uses it: its failures go into the run's record."""
        return _Recorded(self.backend(name), run)

    async def close(self) -> None:
        """Close the backends this harness made."""
        if self._closed:
            return
        self._closed = True
        for backend in self._backends.values():
            await backend.close()

    async def __aenter__(self) -> Harness:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()


def open(
    instance: str | Path,
    *,
    backend: str | None = None,
    settings: Sequence[str | Path] = (),
    params: Mapping[str, str] | None = None,
    person: Person | str | None = None,
    runs: Path | None = None,
) -> Harness:
    """Open the harness on an instance: load `instance` and its `settings` and `params`, and the backend (the instance's, or
    `backend`). `person` is a `Person`, or a name the registry knows (`terminal`, `nobody`); None is nobody. `runs` is where
    runs are kept (default: `<instance directory>/runs`). Whatever stops the run before it can start raises `RunCannotStart`
    (TOOL-16, REG-2, SET-3, INST-1). Tool servers are connected when the first run starts."""
    try:
        return Harness(Path(instance), backend=backend, settings=settings, params=params, person=person, runs=runs)
    except (InstanceError, SettingsError) as e:
        raise RunCannotStart(str(e)) from e
