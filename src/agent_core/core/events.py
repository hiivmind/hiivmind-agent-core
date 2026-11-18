"""The event hub: every unit of the harness emits into it, and `harness.events.record()` reads it back (F15)."""

from agent_core.contracts.events import Event


class EventHub:
    """An `EventSink` that keeps each event of the harness in the order it was emitted."""

    def __init__(self) -> None:
        self._events: list[Event] = []

    def emit(self, event: Event) -> None:
        self._events.append(event)

    def record(self) -> tuple[Event, ...]:
        return tuple(self._events)
