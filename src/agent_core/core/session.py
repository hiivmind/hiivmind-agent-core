"""A session: the core's loop over a person's turns, routing between nodes and sequences (requirements §3.11, ORC-7).

The session's state is the core's own (P25): its facts, the node runs in flight, the transcript, and what resuming needs.
It is saved through a `store` provider after each change a restart must not lose (SS-3).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from agent_core.contracts.context import transcript_handover
from agent_core.contracts.errors import RunCannotStart, SessionWaits, ToolServerError
from agent_core.contracts.events import NodeStarted
from agent_core.contracts.facade import SequenceResult, SessionResult
from agent_core.contracts.person import Person, Question
from agent_core.contracts.store import SessionStore
from agent_core.contracts.tools import ToolSource
from agent_core.contracts.topology import MenuItem
from agent_core.contracts.unit import Unit, UnitResult
from agent_core.contracts.values import FAILED, HarnessReason, ToolSpec
from agent_core.core.brief import make_routing_brief
from agent_core.core.instance import Instance
from agent_core.core.record import new_run_id, now, session_record
from agent_core.core.routing import ENTERED, ROUTING, RoutingPolicy

if TYPE_CHECKING:
    from agent_core.core.facade import Harness, _Run

MENU = "What would you like to do?"

EXIT_HANDLING = ("route", "end")


def check_topology(instance: Instance) -> None:
    """The checks a session makes on the topology when it starts, not when the instance loads, so that an instance that
    runs jobs still loads (SS-12): each exit handling, each menu item, and the improvisation setting."""
    file, topology = instance.entry, instance.topology
    for outcome, handling in topology.exits.items():
        if handling not in EXIT_HANDLING:
            raise RunCannotStart(f"{file}: the exit handling of `{outcome}` is `{handling}`; it must be `route` or `end`")
    for item in topology.menu:
        if item.name not in topology.nodes and item.name not in topology.sequences:
            raise RunCannotStart(f"{file}: the menu item `{item.label}` names `{item.name}`, which is no node or sequence")
    if instance.improvisation == "on":   # diversions are deferred (E10)
        raise RunCannotStart(f"{file}: improvisation is on, and diversions are not built yet (backlog 48)")


def new_state() -> dict:
    """A new session's state (design §3.2). `units` maps a node run's checkpoint thread to its entry; `node` is the thread
    of the active node; `temporary` stays None until diversions are built (backlog 48); `started` counts the session's
    top-level runs."""
    return {
        "facts": {}, "units": {}, "node": None, "temporary": None, "menu_waiting": False, "transcript": [],
        "sequence": None, "status": "open", "started": 0,
    }


class SessionPort:
    """What a node run of the session is given: the session's facts and transcript, its unit entries, and the person as
    the session records them. Each change it makes is saved."""

    def __init__(self, state: dict, store: SessionStore, session_id: str, person: Person):
        self.state, self._store, self.session_id = state, store, session_id
        self.left = asyncio.Event()   # set when the person has gone
        self.replaying = False   # set while a unit in flight is resumed: what it tells again is not added again
        self.recorded: dict[str, dict] = {}   # by thread: the outputs a node run that ended set while it ran (NODE-9)
        self.person = RecordingPerson(person, self)

    @property
    def facts(self) -> dict:
        return self.state["facts"]

    @property
    def transcript(self) -> list:
        return self.state["transcript"]

    def save(self) -> None:
        self._store.save(self.session_id, self.state)

    def unit(self, thread: str) -> dict | None:
        return self.state["units"].get(thread)

    def save_unit(self, thread: str, entry: dict) -> None:
        self.state["units"][thread] = entry
        self.save()

    def pending(self, thread: str, question: str | None) -> None:
        """The question the node run on `thread` waits on, or None once it is answered (ST-1)."""
        entry = self.state["units"].get(thread)
        if entry is not None:
            entry["pending"] = question
            self.save()

    def add(self, entry: dict) -> None:
        """Add a transcript entry and save. While a unit replays, a text equal to the last thing told is not added again
        (design §3.6); the first entry that is added ends the replay."""
        if self.replaying and "agent" in entry:
            told = next((e["agent"] for e in reversed(self.transcript) if "agent" in e), None)
            if told == entry["agent"]:
                return
        self.replaying = False
        self.transcript.append(entry)
        self.save()

    async def node_ended(self, thread: str, node: str, inputs: dict, result: UnitResult, recorded: dict, outputs: tuple[str, ...]) -> None:
        """The one completion path of every node run of the session, top-level, in a sequence or in a fragment (plan review
        A4): tell the person what the model had no turn to say (CTL-8, NODE-9), add the node's transcript entry, keep what
        it recorded for the session's merge, and drop its unit entry. Exit handling and merging facts are the caller's."""
        if result.reason == HarnessReason.INVALID_OUTPUT:
            errors = "; ".join(result.detail.get("errors", ()))
            await self.person.tell(f"`{node}` could not finish: its outputs did not match its output schema: {errors}")
        own = result.outputs.get("reason")
        if own is not None and (result.exit == FAILED or "reason" not in outputs):
            await self.person.tell(f"`{node}` ended `{result.exit}`: {own}")
        entry = {"node": node, "inputs": dict(inputs), "outcome": result.exit}
        if result.exit == FAILED and (result.reason or own):
            entry["reason"] = str(result.reason or own)
        self.add(entry)
        self.recorded[thread] = dict(recorded)
        self.state["units"].pop(thread, None)


class RecordingPerson:
    """The person as the session sees them: what they are told and asked, and what they say, goes into the transcript and
    is saved before it is put to them (SS-3). A None from `ask` or `hear` is a person who has gone: the session waits
    (SS-5)."""

    def __init__(self, person: Person, port: SessionPort):
        self._person, self._port = person, port

    async def tell(self, text: str) -> None:
        self._port.add({"agent": text})
        await self._person.tell(text)

    async def ask(self, question: Question) -> str:
        self._port.add({"agent": question.text})
        return self._heard(await self._person.ask(question))

    async def hear(self) -> str:
        return self._heard(await self._person.hear())

    def _heard(self, reply: str | None) -> str:
        if reply is None:
            self._port.left.set()
            raise SessionWaits()
        self._port.add({"user": reply})
        return reply


class WaitingServers:
    """A run's tool servers in a session (TOOL-11f): a call to a server that cannot be reached does not end the run. The
    person is told, with the server and the tool named, and any reply makes the same call again, until it works or the
    person has gone (SS-5). The model sees only the result that came in the end."""

    def __init__(self, inner: ToolSource, person: RecordingPerson):
        self._inner, self._person = inner, person

    async def tools(self) -> tuple[ToolSpec, ...]:
        return await self._inner.tools()

    async def call(self, name: str, args: dict, state: dict) -> object:
        while True:
            try:
                return await self._inner.call(name, args, state)
            except ToolServerError as e:
                await self._person.tell(f"The {e}. Reply when it is put right, and the call will be made again.")
                await self._person.hear()

    async def close(self) -> None:
        await self._inner.close()


class Session:
    """One session of the person's (design §3.3): its loop over their turns, run in one `_Run` of the harness for its
    length (TOOL-15), with its state saved through `store` as it changes."""

    def __init__(self, harness: Harness, session_id: str, state: dict, store: SessionStore, person: Person):
        self._h, self.id, self.state = harness, session_id, state
        self.port = SessionPort(state, store, session_id, person)
        self.dir = harness.runs / session_id
        self._routed = 0

    async def run(self, name: str | None) -> SessionResult:
        """A new session: entered at `name` by code (GW-4a), or opened with the greeting and the menu (GW-6a, GW-8)."""
        return await self._session(lambda run: self._open(run, name))

    async def resume(self) -> SessionResult:
        return await self._session(self._resume)

    async def _session(self, first: Callable[[_Run], Awaitable[None]]) -> SessionResult:
        h, start = self._h, now()
        run = await h.begin(self.dir, session=self.port)
        try:
            try:
                await first(run)
                await self._loop(run)
            except SessionWaits:   # the person has gone: the session is saved and waits for them (SS-5)
                pass
        finally:
            self.port.save()
            await run.end()
        state = "ended" if self.state["status"] == "ended" else "waiting"
        record = session_record(
            params=h.params, settings_files=h.settings_files, backend=h.backend_name, attended=h.attended, start=start,
            end=now(), failures=run.failures, events=h.hub.record(), labels=run.labels, session_id=self.id, end_state=state,
            facts=self.state["facts"],
        )
        return SessionResult(self.id, state, dict(self.state["facts"]), record, self.dir)

    # --- the loop ------------------------------------------------------------------------------------------------------

    async def _open(self, run: _Run, name: str | None) -> None:
        if name is not None:
            await self._enter(run, name, {}, None)
            return
        if self._h.instance.topology.greeting:
            await self.port.person.tell(self._h.instance.topology.greeting)
        await self._menu()

    async def _loop(self, run: _Run) -> None:
        """Each turn of the person's: a menu item entered by code, or anything else routed (design §3.3)."""
        while self.state["status"] != "ended":
            reply = await self.port.person.hear()
            if self.state["menu_waiting"]:
                item = self._chosen(reply)
                if item is not None:
                    await self._enter(run, item.name, {}, None)
                    continue
                self.state["menu_waiting"] = False
                self.port.save()
            await self._route(run)

    async def _menu(self) -> None:
        menu = self._h.instance.topology.menu
        if not menu:
            return
        self.state["menu_waiting"] = True
        await self.port.person.tell("\n".join([MENU, *(f"{n}. {item.label}" for n, item in enumerate(menu, 1))]))

    def _chosen(self, reply: str) -> MenuItem | None:
        """The menu item a reply names: its number, or its label compared without case (GW-8)."""
        said = reply.strip().casefold()
        for n, item in enumerate(self._h.instance.topology.menu, 1):
            if said in (str(n), item.label.casefold()):
                return item
        return None

    async def _route(self, run: _Run) -> None:
        """The routing run (SCOPE-6): handed the transcript before the person's last turn, and opened with that turn."""
        h = self._h
        self._routed += 1
        label = f"{ROUTING}#{self._routed}"
        run.labels.append(label)
        transcript = self.port.transcript
        resources = run.resources
        guide = resources.read("GATEWAY.md") if resources.exists("GATEWAY.md") else None
        instructions, tools, parts = make_routing_brief(h.instance, guide)
        policy = RoutingPolicy(
            label=label, topology=h.instance.topology, instructions=instructions, tools=tools,
            handover=transcript_handover(transcript[:-1]), opening=transcript[-1]["user"], facts=self.state["facts"],
            check=run.check_node, person=self.port.person, events=h.hub,
        )
        h.hub.emit(NodeStarted(label, ROUTING, parts, tuple(spec.name for spec in tools)))

        async def start(node, inputs, thread):
            return policy

        unit = Unit(ROUTING, {}, "start", f"{self.id}/r{self._routed}", start, run.declared, h.hub, h.instance.topology, run.call)
        result = await h.recorded(None, run).run_node(unit)
        if result.exit == ENTERED:
            entered = result.outputs
            await self._enter(run, entered["name"], entered["inputs"], entered["checked"])

    async def _enter(self, run: _Run, name: str, inputs: dict, checked: dict | None) -> None:
        """Start what a menu item, the command line or the routing run named: a name that is both is the sequence
        (SEQ-12). `checked` holds what the routing run's checks wrote; None, when the checks are still to be made, when
        the node starts."""
        if name in self._h.instance.topology.sequences:
            await self._sequence(name, inputs)
        else:
            await self._node(run, name, inputs, checked)

    async def _sequence(self, name: str, inputs: dict) -> None:
        """A sequence of the session: a run of its own, journalled, which starts from the inputs it was entered with and
        not from the session facts (SS-9). Its node runs are session node runs (design §3.10)."""
        self.state["menu_waiting"] = False
        run_id = new_run_id(name)
        self.state["sequence"] = {"run_id": run_id, "backend": self._h.backend_name, "name": name, "inputs": dict(inputs)}
        self.port.save()
        result = await self._h.sequence(run_id, lambda m: m.start(run_id, name, dict(inputs)), session=self.port)
        await self._sequence_ended(result)

    async def _sequence_ended(self, result: SequenceResult) -> None:
        """The declared outputs its steps returned are merged, in the order they ended (SS-10), and the session returns to
        routing (GW-3, amended 2026-11-16)."""
        entered = self.state["sequence"]
        self.state["facts"].update(result.outputs)
        self.state["sequence"] = None
        self.port.add({"sequence": entered["name"], "inputs": entered["inputs"], "end": result.end})
        await self._menu()

    async def _node(self, run: _Run, name: str, inputs: dict, checked: dict | None) -> None:
        waited = self.state["menu_waiting"]
        self.state["menu_waiting"] = False
        self.state["started"] += 1
        thread = f"{self.id}/{self.state['started']}"
        entry = {"node": name, "inputs": dict(inputs), "backend": run.backend_name}
        if checked is not None:
            entry["checked"] = dict(checked)
        self.state["units"][thread], self.state["node"] = entry, thread
        self.port.save()
        result = await self._h.recorded(run.backend_name, run).run_node(run.unit(name, inputs, "start", thread))
        await self._ended(thread, name, result, waited)

    async def _ended(self, thread: str, name: str, result: UnitResult, waited: bool = False) -> None:
        """After a top-level node run: its facts merged (ST-2, NODE-9), then its exit handling (GW-3, Q1). A node whose
        checks refused it did not run: the person is told why, and the menu waits as it did (GW-4b)."""
        port, state = self.port, self.state
        state["node"] = None
        if thread in state["units"]:   # it did not start: `node_ended` was not reached
            entry = state["units"].pop(thread)
            message = result.detail.get("message") or result.detail.get("detail")
            if message:
                await port.person.tell(message)
            if result.reason == HarnessReason.PRECONDITION_UNMET:
                state["menu_waiting"] = waited
                port.save()
                return
            port.add({"node": name, "inputs": entry["inputs"], "outcome": result.exit,
                      **({"reason": str(result.reason)} if result.exit == FAILED and result.reason else {})})
        declared = self._h.instance.nodes[name].contract.outputs
        state["facts"].update(port.recorded.pop(thread, {}))
        state["facts"].update({k: v for k, v in result.outputs.items() if k in declared})
        if self._h.instance.topology.exits.get(result.exit, "route") == "end":
            state["status"] = "ended"
            port.save()
            return
        port.save()
        await self._menu()

    # --- resuming ------------------------------------------------------------------------------------------------------

    async def _resume(self, run: _Run) -> None:
        """Carry on from where the session stopped (design §3.5)."""
        state, port = self.state, self.port
        transcript = port.transcript
        if state["sequence"] is not None:   # resumed by its journal, every unit on the backend it started with (ST-4)
            sequence = state["sequence"]
            run_id = sequence["run_id"]
            port.replaying = True
            result = await self._h.sequence(
                run_id, lambda m: m.resume(run_id), session=port, backend=sequence["backend"],
            )
            await self._sequence_ended(result)
        elif state["node"] is not None:   # a unit in flight: continued on its thread, on the backend that started it (SS-11)
            thread = state["node"]
            entry = state["units"][thread]
            port.replaying = True
            unit = run.unit(entry["node"], entry["inputs"], "continue", thread)
            result = await self._h.recorded(entry["backend"], run).run_node(unit)
            await self._ended(thread, entry["node"], result)
        elif state["menu_waiting"]:
            port.replaying = True
            await self._menu()
        elif transcript and "user" in transcript[-1]:   # the routing run stopped before it entered anything
            await self._route(run)
        elif transcript and "agent" in transcript[-1]:
            port.replaying = True
            await port.person.tell(transcript[-1]["agent"])
