"""A session: the core's loop over a person's turns, routing between nodes and sequences (requirements §3.11, ORC-7).

The session's state is the core's own (P25): its facts, the node runs in flight, the transcript, and what resuming needs.
It is saved through a `store` provider after each change a restart must not lose (SS-3).
"""

import asyncio

from agent_core.contracts.errors import RunCannotStart, SessionWaits
from agent_core.contracts.person import Person, Question
from agent_core.contracts.store import SessionStore
from agent_core.contracts.unit import UnitResult
from agent_core.contracts.values import FAILED, HarnessReason
from agent_core.core.instance import Instance

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
