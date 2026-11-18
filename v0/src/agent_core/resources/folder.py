from pathlib import Path

from agent_core.contracts.registry import register


@register("resources", "folder")
class FolderResources:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def _resolve(self, path: str) -> Path:
        full = (self.root / path).resolve()
        if not full.is_relative_to(self.root):
            raise ValueError(f"path `{path}` leaves the folder {self.root}")
        return full

    def read(self, path: str) -> str:
        full = self._resolve(path)
        try:
            return full.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise FileNotFoundError(f"no file `{path}` in {self.root}") from None

    def exists(self, path: str) -> bool:
        return self._resolve(path).exists()
