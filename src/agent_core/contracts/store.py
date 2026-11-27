"""Where a session's state is kept between units and across processes (ST-4, P25). Standard library only."""

from typing import Protocol


class SessionStore(Protocol):
    def load(self, session_id: str) -> dict | None: ...   # None: the store holds no session of that id
    def save(self, session_id: str, state: dict) -> None: ...   # the whole state, replacing the last saved one
