import shutil
from pathlib import Path

import pytest

from agent_core.core.instance import load_instance
from agent_core.core.settings import load_settings
from agent_core.core.templates import render
from agent_core.resources.folder import FolderResources

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "instance"


class Broken:
    """A copy of the fixture instance in `root`, edited one file at a time."""

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
        file = self.root / "skills" / node / "SKILL.md"
        head, rest = file.read_text().split("\n---\n", 1)
        lines = [line for line in head.splitlines() if line.split(":")[0] not in keys or line.startswith(" ")]
        lines += [f"{k}: {v}" for k, v in keys.items()]
        file.write_text("\n".join(lines) + "\n---\n" + rest)


@pytest.fixture
def instance():
    return load_instance(FIXTURE / "instance.yaml", FolderResources(FIXTURE))


@pytest.fixture
def broken(tmp_path):
    root = tmp_path / "instance"
    shutil.copytree(FIXTURE, root, ignore=shutil.ignore_patterns("__pycache__"))
    return Broken(root)


@pytest.fixture
def load(broken):
    def load_copy():
        return load_instance(broken.root / "instance.yaml", FolderResources(broken.root))

    return load_copy


@pytest.fixture
def render_text(instance):
    """Render `text` against the fixture instance; the settings are the fixture's with `alpha.yaml` layered over."""
    settings = load_settings(instance, [instance.root / "config" / "alpha.yaml"])

    def render_it(text, *, file="skills/example/SKILL.md", inputs=None, session=None, values=None):
        return render(
            text,
            file=file,
            settings=settings,
            inputs=inputs or {},
            session=session or {},
            values=values or {},
            resources=FolderResources(instance.root),
        )

    return render_it


@pytest.fixture
def render_refresh(instance, render_text):
    """Render the body of the fixture's `refresh` node."""
    node = instance.nodes["refresh"]

    def render_node(**kwargs):
        return render_text(node.body, file=node.file, **kwargs)

    return render_node


@pytest.fixture
def refresh_node(instance):
    """The fixture's `refresh` node: input `sources`; outputs `sources_updated` and `branch`."""
    return instance.nodes["refresh"]
