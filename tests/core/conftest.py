import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest

from agent_core.backends.scripted import ScriptedBackend
from agent_core.contracts import Brief
from agent_core.core.controller import VERB_SPECS, Controller, NodeRun
from agent_core.core.instance import load_instance
from agent_core.core.settings import load_settings
from agent_core.core.state import HarnessState, Slot
from agent_core.core.templates import render
from agent_core.person.nobody import Nobody
from agent_core.resources.folder import FolderResources
from agent_core.tools.function import FunctionSource
from agent_core.tools.mcp_server import McpServerSource

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


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    """The run's directory: the fixture servers and functions record their calls here."""
    directory = tmp_path / "run"
    directory.mkdir()
    monkeypatch.setenv("AGENT_CORE_RUN_DIR", str(directory))
    return directory


@dataclass
class Ran:
    """What `run_node` returns: the controller's work, as the run left it."""

    run: NodeRun
    brief: Brief
    controller: Controller

    def __getattr__(self, name):
        return getattr(self.run, name)

    @property
    def slot_rejections(self) -> int:
        return self.run.slot.rejections


@pytest.fixture
def run_node(instance, run_dir):
    """Run one node of the fixture instance through a driver and the controller, with real tools."""

    async def run(node_name, inputs, script=None, *, driver=None, person=None, label=None, session=None):
        node = instance.nodes[node_name]
        settings = load_settings(instance, [FIXTURE / "config" / "alpha.yaml"])
        env = {"AGENT_CORE_INSTANCE": str(FIXTURE), "AGENT_CORE_RUN_DIR": str(run_dir)}
        sources = [FunctionSource(instance.functions, settings, FIXTURE), McpServerSource(instance.servers, env, FIXTURE)]
        try:
            tools = {spec.name: (source, spec) for source in sources for spec in await source.tools()}
            state = HarnessState(session=dict(session or {}))
            slot = state.node = Slot(node.name, dict(inputs), {}, {})
            offered = ("exit", "ask", "state_set", "state_get", "load", *node.allowed_tools)
            specs = {**{n: VERB_SPECS[n] for n in offered[:5]}, **{n: tools[n][1] for n in node.allowed_tools}}
            brief = Brief(
                instructions=f"# Procedure of the node that is running: `{node.name}`\n",
                tools=tuple(specs.values()),
                handover=(),
                opening="Run the node.",
            )
            node_run = NodeRun(
                node=node, slot=slot, state=state, offered=frozenset(offered), tools=tools,
                functions=frozenset(instance.functions), person=person or Nobody(),
                resources=FolderResources(FIXTURE), job=True, label=label or f"{node.name}#1", record=[], usage=[],
            )
            controller = Controller(node_run)
            await (driver or ScriptedBackend(script=script)).drive(brief, controller)
            return Ran(node_run, brief, controller)
        finally:
            for source in sources:
                await source.close()

    return run
