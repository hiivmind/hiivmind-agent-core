"""A session: the core's loop over a person's turns, routing between nodes and sequences (requirements §3.11, ORC-7)."""

from agent_core.contracts.errors import RunCannotStart
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
