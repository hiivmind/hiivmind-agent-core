"""The `file` store: each session is `session.json` in its own directory, `<runs>/<session id>/` (SS-4)."""

import json
import os
from pathlib import Path

from agent_core.contracts.registry import register


@register("store", "file")
class FileStore:
    def __init__(self, runs: Path):
        self._runs = Path(runs)

    def _file(self, session_id: str) -> Path:
        return self._runs / session_id / "session.json"

    def load(self, session_id: str) -> dict | None:
        file = self._file(session_id)
        return json.loads(file.read_text()) if file.is_file() else None

    def save(self, session_id: str, state: dict) -> None:
        """Written whole: to a file beside it, then renamed over it, so that a crash leaves the last saved state."""
        file = self._file(session_id)
        text = json.dumps(state, indent=2)   # before anything is written: a value JSON cannot hold changes nothing
        file.parent.mkdir(parents=True, exist_ok=True)
        temporary = file.with_name(f"{file.name}.tmp")
        temporary.write_text(text)
        os.replace(temporary, file)
