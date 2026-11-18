import dataclasses
import json
import os
import shutil
import subprocess
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest
from walking import SEQUENCES, Nodes

from agent_core.backends.scripted import ScriptedBackend
from agent_core.contracts import Brief, ToolServerError
from agent_core.core.checks import unmet_check
from agent_core.core.controller import Controller, NodeRun
from agent_core.core.instance import load_instance
from agent_core.core.node_runner import NodeRunner
from agent_core.core.record import NodeRunNote
from agent_core.core.registry import provider
from agent_core.core.sequences import SequenceRunner
from agent_core.core.settings import load_settings
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
    """What `run_node` returns: what `NodeRunner.run` gave, and the work of the controller behind it.

    `result` is the dict `run` returned (None when it raised); `run.result` is what the controller itself ended with.
    `run`, `brief` and `controller` are None when no driver was called.
    """

    run: NodeRun | None
    brief: Brief | None
    controller: Controller | None
    result: dict | None
    note: NodeRunNote | None
    fault: Exception | None

    def __getattr__(self, name):
        return getattr(self.run, name)

    @property
    def slot_rejections(self) -> int:
        return self.run.slot.rejections


class Capture:
    """Wraps a driver to keep the brief and the controller it was given; seeds the session facts the test names."""

    def __init__(self, driver, session):
        self.driver, self.session = driver, session
        self.brief: Brief | None = None
        self.controller: Controller | None = None

    async def drive(self, brief, controller):
        self.brief, self.controller = brief, controller
        controller.run.state.session.update(self.session)  # after the brief: the facts only the calls of the run read
        return await self.driver.drive(brief, controller)


@pytest.fixture
def open_runner(instance, run_dir):
    """`open_runner()` is an async context manager giving a `NodeRunner` over the fixture's real tools.

    `target` is an instance whose nodes are run (a copy edited by `broken`); the tools are always the fixture's.
    """

    @asynccontextmanager
    async def open_it(*, person=None, notes=None, target=None):
        target = target or instance
        settings = load_settings(target, [FIXTURE / "config" / "alpha.yaml"])
        env = {"AGENT_CORE_INSTANCE": str(FIXTURE), "AGENT_CORE_RUN_DIR": str(run_dir)}
        sources = [FunctionSource(instance.functions, settings, FIXTURE), McpServerSource(instance.servers, env, FIXTURE)]
        try:
            tools = {spec.name: (source, spec) for source in sources for spec in await source.tools()}
            yield NodeRunner(
                target, settings, tools, frozenset(instance.functions), person or Nobody(),
                FolderResources(target.root), notes if notes is not None else [],
            )
        finally:
            for source in sources:
                await source.close()

    return open_it


@pytest.fixture
def run_node(open_runner):
    """Run one node of the fixture instance through `NodeRunner.run`, with real tools. A dead tool server is kept as `fault`."""

    async def run(node_name, inputs, script=None, *, driver=None, person=None, label=None, session=None, target=None):
        notes: list[NodeRunNote] = []
        async with open_runner(person=person, notes=notes, target=target) as runner:
            capture = Capture(driver or ScriptedBackend(script=script), session or {})
            result, fault = None, None
            try:
                result = await runner.run(node_name, inputs, driver=capture, label=label or f"{node_name}#1")
            except ToolServerError as e:
                fault = e
            controller = capture.controller
            return Ran(
                controller.run if controller else None, capture.brief, controller, result,
                notes[-1] if notes else None, fault,
            )

    return run


# --- the command line ---------------------------------------------------------------------------------------------

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "tests" / "fixtures" / "scripts"
ALPHA = FIXTURE / "config" / "alpha.yaml"


@pytest.fixture
def make_instance(tmp_path):
    """The fixture instance, as the path of its `instance.yaml`.

    Given `instance_with` (a line added under `tools:`), `instance_with_lines` (lines added at the top level) or
    `instance_replace` (a text and its replacement) or `files` (relative path -> text, written into the copy), it is a copy in a temporary directory, with the fixture's
    servers beside it, edited as asked.
    """

    def make(instance_with=None, instance_with_lines=(), instance_replace=None, files=None) -> Path:
        if instance_with is None and not instance_with_lines and instance_replace is None and not files:
            return FIXTURE / "instance.yaml"
        base = tmp_path / "copy"
        root = base / "instance"
        ignore = shutil.ignore_patterns("__pycache__")
        shutil.copytree(FIXTURE, root, ignore=ignore)
        shutil.copytree(FIXTURE.parent / "servers", base / "servers", ignore=ignore)
        text = (root / "instance.yaml").read_text()
        if instance_replace is not None:
            old, new = instance_replace
            assert old in text
            text = text.replace(old, new)
        lines = text.splitlines()
        if instance_with is not None:
            lines.insert(lines.index("tools:") + 1, f"  {instance_with}")
        lines += instance_with_lines
        (root / "instance.yaml").write_text("\n".join(lines) + "\n")
        for name, content in (files or {}).items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(content)
        return root / "instance.yaml"

    return make


class Finished:
    """What the command did: its exit code, `record.json` of its run directory ({} if none), its standard output."""

    def __init__(self, code: int, record: dict, out: str, run_dir: Path):
        self.code, self.record, self.out, self.run_dir = code, record, out, run_dir

    def __iter__(self):
        return iter((self.code, self.record))


def _command(instance_yaml: Path, name: str, run_dir: Path, settings, params, flags) -> list[str]:
    command = [sys.executable, "-m", "agent_core.core.cli", "job", str(instance_yaml), name, "--run-dir", str(run_dir)]
    for file in settings:
        command += ["--settings", str(file)]
    for key, value in params.items():
        command += ["--param", f"{key}={value}"]
    return command + list(flags)


def _environment(case: str) -> dict:
    return {**os.environ, "AGENT_CORE_SCRIPTED_SCRIPTS": str(SCRIPTS / case)}


def _record(run_dir: Path) -> dict:
    file = run_dir / "record.json"
    return json.loads(file.read_text()) if file.exists() else {}


@pytest.fixture
def job(tmp_path, make_instance):
    """`job(name, case="ok", ...)` runs `python -m agent_core.core.cli job` in a subprocess, with the scripts of `case`.

    It gives the fixture instance, `config/alpha.yaml` as the settings file (the instance needs `CORPUS_REPO`), and
    standard input that is not a terminal. `args` are more command line arguments; `settings` and `params` replace
    the default settings files and add `--param`s.
    """

    def run(name, case="ok", *, args=(), settings=(ALPHA,), params=None, **instance_edits) -> Finished:
        run_dir = tmp_path / "run"
        command = _command(make_instance(**instance_edits), name, run_dir, settings, params or {}, args)
        done = subprocess.run(
            command, capture_output=True, text=True, cwd=REPO, env=_environment(case), stdin=subprocess.DEVNULL, timeout=300
        )
        return Finished(done.returncode, _record(run_dir), done.stdout, run_dir)

    return run


@pytest.fixture
def pty_job(tmp_path, make_instance):
    """`pty_job(name, typed=...)` runs the command with a pseudo-terminal as standard input and types `typed` into it.

    Returns what the command printed and its run record. The scripts are those of `case`, "missing" by default: the
    one in which `refresh` asks first.
    """
    import pty

    def run(name, *, typed, case="missing", args=()):
        run_dir = tmp_path / "run"
        command = _command(make_instance(), name, run_dir, (ALPHA,), {}, args)
        master, slave = pty.openpty()
        child = subprocess.Popen(
            command, stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=REPO, env=_environment(case)
        )
        os.close(slave)
        os.write(master, (typed + "\n").encode())  # typed ahead: the terminal holds it until the job reads
        try:
            out, _ = child.communicate(timeout=300)
        finally:
            os.close(master)
        return out, _record(run_dir)

    return run


# --- walking a sequence --------------------------------------------------------------------------------------------


@pytest.fixture
def seq_instance():
    return load_instance(SEQUENCES / "instance.yaml", FolderResources(SEQUENCES))


@pytest.fixture
def walk(seq_instance, tmp_path, monkeypatch):
    """`await walk(name, facts, nodes=Nodes(), check=None, sequences=None)` walks a sequence of the sequences fixture
    with the `none` journal. The checks and tools are the fixture's own; `sequences` adds or replaces sequences."""
    monkeypatch.setenv("AGENT_CORE_RUN_DIR", str(tmp_path))
    source = FunctionSource(seq_instance.functions, None, SEQUENCES)
    tools = {name: (source, None) for name in seq_instance.functions}

    async def real_check(checks, facts, owner):
        return await unmet_check(checks, facts, owner=owner, tools=tools, functions=set(tools), fill=str)

    async def call_tool(tool, args):
        return await source.call(tool, args, {})

    async def run(name, facts=None, *, nodes=None, check=None, sequences=None):
        instance = dataclasses.replace(seq_instance, sequences={**seq_instance.sequences, **(sequences or {})})
        runner = SequenceRunner(instance, nodes or Nodes(), call_tool, check or real_check)
        return await provider("journal", "none")().start("run-1", runner.walk, name, dict(facts or {}))

    return run


class SeqJob:
    """`agent-core job` on the sequences fixture, in a subprocess; each run has its own directory under `tmp_path`.

    `scripts` replaces the scripted backend's script of the nodes it names (a missing node script: `None`); `env` adds
    environment variables; `files` (relative path -> text) makes the instance a copy with those files written.
    """

    def __init__(self, tmp_path: Path):
        self.tmp_path = tmp_path

    def command(self, name, *, run="run", args=(), scripts=None, env=None, files=None) -> tuple[list[str], dict, Path]:
        instance = SEQUENCES / "instance.yaml"
        if files:
            root = self.tmp_path / "copy" / "instance"
            if not root.exists():
                shutil.copytree(SEQUENCES, root, ignore=shutil.ignore_patterns("__pycache__"))
            for file, text in files.items():
                (root / file).parent.mkdir(parents=True, exist_ok=True)
                (root / file).write_text(text)
            instance = root / "instance.yaml"
        directory = SEQUENCES / "scripts" / "ok"
        if scripts:
            directory = self.tmp_path / f"scripts-{run}"
            shutil.copytree(SEQUENCES / "scripts" / "ok", directory, dirs_exist_ok=True)
            for node, script in scripts.items():
                (directory / f"{node}.json").unlink(missing_ok=True)
                if script is not None:
                    (directory / f"{node}.json").write_text(json.dumps(script))
        run_dir = self.tmp_path / run
        command = [sys.executable, "-m", "agent_core.core.cli", "job", str(instance), name, "--run-dir", str(run_dir), *args]
        environment = {**os.environ, "AGENT_CORE_SCRIPTED_SCRIPTS": str(directory), **(env or {})}
        return command, environment, run_dir

    def __call__(self, name, **options) -> Finished:
        command, environment, run_dir = self.command(name, **options)
        done = subprocess.run(
            command, capture_output=True, text=True, cwd=REPO, env=environment, stdin=subprocess.DEVNULL, timeout=300
        )
        return Finished(done.returncode, _record(run_dir), done.stdout + done.stderr, run_dir)

    def start(self, name, **options) -> tuple[subprocess.Popen, Path]:
        command, environment, run_dir = self.command(name, **options)
        child = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=REPO, env=environment,
            stdin=subprocess.DEVNULL,
        )
        return child, run_dir


@pytest.fixture
def seq_job(tmp_path):
    return SeqJob(tmp_path)
