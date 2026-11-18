import copy

from agent_core.contracts.registry import register


@register("store", "memory")
class MemoryStore:
    """Keeps each session's dict in this process. Saving and loading copy, as a store that writes to disk would."""

    def __init__(self):
        self._sessions: dict[str, dict] = {}

    def load(self, session: str) -> dict | None:
        saved = self._sessions.get(session)
        return None if saved is None else copy.deepcopy(saved)

    def save(self, session: str, state: dict) -> None:
        self._sessions[session] = copy.deepcopy(state)
