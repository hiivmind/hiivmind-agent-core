import shutil
from pathlib import Path

from agent_core.core.instance import load_instance

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
FIXTURE = FIXTURES / "instance"
SEQUENCES = FIXTURES / "sequences"


class FolderSource:
    """A test-local ResourceSource over a folder (the provider `resources/folder.py` is not core's to import)."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def read(self, path: str) -> str:
        return (self.root / path).read_text()

    def exists(self, path: str) -> bool:
        return (self.root / path).exists()


class Broken:
    """A copy of a fixture instance in `root`, edited one file at a time."""

    def __init__(self, root: Path):
        self.root = root

    def __call__(self, path: str, text: str) -> None:
        (self.root / path).write_text(text)

    def append(self, path: str, text: str) -> None:
        with (self.root / path).open("a") as f:
            f.write(text)

    def remove_key(self, path: str, key: str) -> None:
        file = self.root / path
        file.write_text("".join(line for line in file.read_text().splitlines(True) if not line.startswith(f"{key}:")))

    def frontmatter(self, node: str, **keys) -> None:
        """Set top-level frontmatter keys of a node file; a value is written as the bare word it is."""
        file = self.root / "nodes" / f"{node}.md"
        head, rest = file.read_text().split("\n---\n", 1)
        lines = [line for line in head.splitlines() if line.split(":")[0] not in keys or line.startswith(" ")]
        lines += [f"{k}: {v}" for k, v in keys.items()]
        file.write_text("\n".join(lines) + "\n---\n" + rest)


def load(root: Path):
    return load_instance(root / "instance.yaml", FolderSource(root))
