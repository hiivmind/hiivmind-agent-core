"""Run a job: open the instance's tools, run the script or walk the sequence, keep the record (JOB-1 to JOB-17)."""

import hashlib
import importlib.util
import inspect
import json
import os
import sys
from collections.abc import AsyncIterator, Callable, Iterator, Mapping, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from pydantic import SecretBytes, SecretStr

from agent_core.contracts.backend import NodeDriver
from agent_core.contracts.errors import ToolServerError
from agent_core.contracts.person import Person
from agent_core.contracts.state import StateStore
from agent_core.contracts.tools import ToolSource
from agent_core.contracts.values import ToolSpec
from agent_core.core.checks import unmet_check
from agent_core.core.instance import Instance, InstanceError, load_instance
from agent_core.core.node_runner import NodeRunner
from agent_core.core.record import RunRecord
from agent_core.core.registry import BackendNotInstalled, UnknownBackend, provider
from agent_core.core.registry import backend as known_backend
from agent_core.core.sequences import SequenceRunner
from agent_core.core.settings import SettingsError, load_settings
from agent_core.core.state import HarnessState, from_dict, to_dict
from agent_core.core.templates import render


class RunCannotStart(Exception):
    """The run stops before the job starts. The message is the one line the command prints."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class _Asking:
    """The person, as one node run sees them: a question carries the run's label and the values of its inputs (JOB-6)."""

    def __init__(self, person: Person, inputs: Mapping):
        self._person, self._inputs = person, inputs

    async def tell(self, text: str) -> None:
        await self._person.tell(text)

    async def ask(self, question: str, label: str = "") -> str | None:
        return await self._person.ask(question, " ".join([label, *(str(v) for v in self._inputs.values())]))


class Run:
    """An open run: the instance, its settings and tools, and the record. Made by `open_run`."""

    def __init__(
        self,
        instance: Instance,
        settings: object | None,
        tools: dict[str, tuple[ToolSource, ToolSpec]],
        person: Person,
        store: StateStore,
        record: RunRecord,
        run_dir: Path,
    ):
        self.instance, self.settings, self.record, self.run_dir = instance, settings, record, run_dir
        self.person, self.store = person, store
        self._tools = tools
        self._functions = frozenset(instance.functions)
        self._resources = provider("resources", "folder")(instance.root)
        self._drivers: dict[str, NodeDriver] = {}
        self._started = 0

    async def call(self, tool: str, args: dict) -> object:
        """Call a tool the instance declares, as a node's CALL does. A function's own value comes back; a server's text
        comes back parsed as JSON where it parses (JOB-2). A function is given no state."""
        if tool not in self._tools:
            raise ValueError(f"no tool `{tool}`; the tools are: {', '.join(self._tools)}")
        value = await self._tools[tool][0].call(tool, args, {})
        if tool in self._functions or not isinstance(value, str):
            return value
        try:
            return json.loads(value)
        except ValueError:
            return value

    def _driver(self, name: str) -> NodeDriver:
        if name not in self._drivers:
            cls, settings_cls = known_backend(name)
            self._drivers[name] = cls(settings_cls())  # the backend's settings read their own environment (R11)
        return self._drivers[name]

    async def run_node(self, node: str, inputs: dict, backend: str | None = None, *, driver: NodeDriver | None = None) -> dict:
        """Run one node from fresh facts and return its result. The backend is `backend`, else the run's (REG-2).

        A tool server that cannot be reached raises, and the record names the node (TOOL-11e); a failed result does not
        fail the job, it is recorded (JOB-9b).
        """
        chosen = driver or self._driver(backend or self.record.backend)
        self._started += 1
        label = f"{node}#{self._started}"
        saved = self.store.load(label)  # nothing: a label is used once
        state = HarnessState(session={}) if saved is None else from_dict(saved)
        runner = NodeRunner(
            self.instance, self.settings, self._tools, self._functions, _Asking(self.person, inputs), self._resources,
            self.record.notes,
        )
        try:
            result = await runner.run(node, inputs, driver=chosen, label=label, state=state)
        except ToolServerError as e:
            self.record.failures.append({"node": node, "error": f"{type(e).__name__}: {e}"})
            raise
        finally:
            self.store.save(label, to_dict(state))
        if result.get("outcome") == "failed":
            self.record.failures.append({"node": node, **result})
        return result

    async def check(self, checks: Sequence[dict], facts: dict, owner: str) -> tuple[dict | None, dict]:
        """A sequence's checks, against its facts: `input` placeholders in their args are the facts (§4.2)."""

        def fill(text: str) -> str:
            return render(
                text, file=f"sequence {owner}", settings=self.settings, inputs=facts, session={}, values={},
                resources=self._resources,
            )

        return await unmet_check(checks, facts, owner=owner, tools=self._tools, functions=set(self._functions), fill=fill)


class Job:
    """What a job script is given: the settings, `call`, and `run_node`."""

    def __init__(self, run: Run):
        self._run = run
        self.settings = run.settings

    async def call(self, tool: str, args: dict) -> object:
        return await self._run.call(tool, args)

    async def run_node(self, node: str, inputs: dict, backend: str | None = None) -> dict:
        return await self._run.run_node(node, inputs, backend)


def _restore(before: Mapping[str, str | None]) -> None:
    for key, value in before.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@asynccontextmanager
async def open_run(
    instance_yaml: Path,
    *,
    settings_files: Sequence[Path | str] = (),
    params: Mapping[str, str] | None = None,
    run_dir: Path,
    attended: bool = False,
    backend: str | None = None,
) -> AsyncIterator[Run]:
    """Load the instance, its settings and tools, a person and a store; close each tool source on the way out.

    Whatever stops the run before the job can start raises `RunCannotStart` (TOOL-16, REG-2, SET-3, INST-1).
    """
    instance_yaml, run_dir = Path(instance_yaml), Path(run_dir).resolve()
    async with AsyncExitStack() as stack:
        root = str(instance_yaml.resolve().parent)
        sys.path.insert(0, root)  # the instance's own files import each other by name (`from tools.sources import X`)
        stack.callback(sys.path.remove, root)
        try:
            instance = load_instance(instance_yaml, provider("resources", "folder")(instance_yaml.resolve().parent))
            settings = load_settings(instance, [Path(f) for f in settings_files], params)
            backend_name = backend or instance.backend
            known_backend(backend_name)  # the one the script gets unless it names another: known and installed
        except (InstanceError, SettingsError, UnknownBackend, BackendNotInstalled) as e:
            raise RunCannotStart(str(e)) from e
        run_dir.mkdir(parents=True, exist_ok=True)
        given = {"AGENT_CORE_INSTANCE": str(instance.root), "AGENT_CORE_RUN_DIR": str(run_dir)}
        stack.callback(_restore, {key: os.environ.get(key) for key in given})  # in this process: the functions read them too
        os.environ.update(given)
        tools = await _open_tools(stack, instance, settings)
        record = RunRecord(
            params=_masked(params or {}, settings), settings_files=[str(f) for f in settings_files], backend=backend_name,
            attended=attended, start=_now(),
        )
        person = provider("person", "terminal" if attended else "nobody")()
        yield Run(instance, settings, tools, person, provider("store", "memory")(), record, run_dir)


def _masked(params: Mapping[str, str], settings: object | None) -> dict[str, str]:
    """The params as the record keeps them: a value of a setting that is a secret is not written."""
    return {
        key: "********" if isinstance(getattr(settings, key, None), (SecretStr, SecretBytes)) else value
        for key, value in params.items()
    }


def _one_line(e: BaseException) -> str:
    return " ".join(f"{type(e).__name__}: {e}".split())


def _make(label: str, build: Callable[[], ToolSource]) -> ToolSource:
    """A tool source made by `build`; whatever it raises is a run that cannot start, named by `label`."""
    try:
        return build()
    except Exception as e:
        raise ValueError(f"instance.yaml: {label}: {_one_line(e)}") from e


def _declared(instance: Instance, settings: object | None) -> Iterator[tuple[ToolSource, Callable[[str], str]]]:
    """Each tool source of the instance, made as it is asked for, with how a tool of it is described in a refusal."""
    yield (
        provider("tool_source", "tools")(instance.functions, settings, instance.root),
        lambda name: f"function {instance.functions[name]}",
    )
    yield (
        _make("tool servers", lambda: provider("tool_source", "servers")(instance.servers, dict(os.environ), instance.root)),
        lambda name: f'server "{name.partition("__")[0]}"',
    )
    for key, entry in instance.sources.items():
        built = _make(f'source "{key}"', lambda: provider("tool_source", entry["provider"])(key, entry, instance.root))
        yield built, lambda name, key=key: f'source "{key}"'


async def _open_tools(
    stack: AsyncExitStack, instance: Instance, settings: object | None
) -> dict[str, tuple[ToolSource, ToolSpec]]:
    """Open the functions, the servers and the instance's own sources; list their tools; each is named once (TOOL-16)."""
    opened: list[tuple[ToolSource, Callable[[str], str]]] = []
    try:
        for source, describe in _declared(instance, settings):
            stack.push_async_callback(source.close)
            opened.append((source, describe))
    except ValueError as e:  # a function cannot be imported; a source cannot be made
        raise RunCannotStart(" ".join(str(e).split())) from e
    tools: dict[str, tuple[ToolSource, ToolSpec]] = {}
    owner: dict[str, str] = {}
    for source, describe in opened:
        try:
            specs = await source.tools()  # a server that cannot be started is found now, not in the middle of the job
        except ToolServerError as e:
            raise RunCannotStart(str(e)) from e
        for spec in specs:
            if spec.name in tools:
                raise RunCannotStart(
                    f'instance.yaml: two tools are named "{spec.name}": {owner[spec.name]} and {describe(spec.name)}'
                )
            tools[spec.name], owner[spec.name] = (source, spec), describe(spec.name)
    return tools


def _job_main(root: Path, name: str) -> Callable:
    """The `main` of the file `<instance>/jobs/<name>.py`, imported by path (R11)."""
    file = root / "jobs" / f"{name}.py"
    missing = RunCannotStart(f"no job `{name}` in {root}/jobs/")
    if not file.is_file():
        raise missing
    module_name = f"_agent_core_job_{hashlib.sha256(str(file).encode()).hexdigest()[:16]}_{name}"
    spec = importlib.util.spec_from_file_location(module_name, file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[module_name]
        raise
    main = getattr(module, "main", None)
    if not inspect.iscoroutinefunction(main):
        raise missing
    return main


def _unknown(instance: Instance, name: str) -> str:
    scripts = sorted(file.stem for file in (instance.root / "jobs").glob("*.py"))
    return (
        f"no sequence or job script `{name}`; the sequences are: {', '.join(sorted(instance.sequences)) or 'none'}; "
        f"the job scripts are: {', '.join(scripts) or 'none'}"
    )


async def _run_sequence(
    run: Run, name: str, inputs: dict, resume: str | None, rerun_from: tuple[str, int] | None
) -> None:
    """Walk the sequence `name` as one journalled run, and fill the record (§4.6, §4.7)."""
    record = run.record
    run_id = resume or run.run_dir.name
    record.run_id, record.steps = run_id, []
    print(f"run {run_id}" + (f" (from {rerun_from[0]}, step {rerun_from[1]})" if rerun_from else ""), flush=True)
    runner = SequenceRunner(run.instance, run.run_node, run.call, run.check)
    journal = provider("journal", "dbos")(run.run_dir.parent / "journal.sqlite", run.instance.name, run_id)
    try:
        if resume:
            result = await journal.resume(run_id, runner.walk)
        elif rerun_from:
            result = await journal.rerun(run_id, rerun_from[0], rerun_from[1], runner.walk)
        else:
            result = await journal.start(run_id, runner.walk, name, inputs)
    except Exception as e:  # the run raised, or DBOS refused it (an unknown id): the run failed (JOB-17)
        record.summary, record.status = f"{type(e).__name__}: {e}", "failed"
        print(f"error: {record.summary}", flush=True)
        return
    finally:
        await journal.close()
    record.end_state, record.steps, record.facts, record.summary = (
        result["end"], result["trail"], result["facts"], result["summary"]
    )
    record.status = "failed" if result["end"] == "failed" else "ok"
    if result["end"] == "failed":
        print(f"sequence `{name}` ended failed: {result['summary']}", flush=True)
    elif isinstance(result["summary"], str):
        print(result["summary"], flush=True)


async def run_job(
    instance_yaml: Path,
    name: str,
    *,
    settings_files: Sequence[Path | str] = (),
    params: Mapping[str, str] | None = None,
    no_ask: bool = False,
    backend: str | None = None,
    run_dir: Path,
    inputs: Mapping[str, str] | None = None,
    resume: str | None = None,
    rerun_from: tuple[str, int] | None = None,
) -> int:
    """Run the sequence or job script `name` of the instance and write `record.json`.

    Returns the exit code: 0 ok, 1 failed, 2 could not start. `inputs`, `resume` and `rerun_from` apply to a sequence.
    """
    attended = sys.stdin is not None and sys.stdin.isatty() and not no_ask  # JOB-6
    try:
        async with open_run(
            instance_yaml, settings_files=settings_files, params=params, run_dir=run_dir, attended=attended, backend=backend
        ) as run:
            record = run.record
            record.job = name
            sequence = name in run.instance.sequences
            script = (run.instance.root / "jobs" / f"{name}.py").is_file()
            if sequence and script:  # JOB-15
                raise RunCannotStart(f"`{name}` is both a job script and a sequence")
            if not sequence and not script:
                raise RunCannotStart(_unknown(run.instance, name))
            if sequence:  # JOB-14
                await _run_sequence(run, name, dict(inputs or {}), resume, rerun_from)
            else:
                try:
                    record.summary = await _job_main(run.instance.root, name)(Job(run))
                    record.status = "ok"
                except RunCannotStart:
                    raise
                except Exception as e:  # the script decided the job failed, or broke (JOB-9b)
                    record.summary, record.status = f"{type(e).__name__}: {e}", "failed"
            record.end = _now()
            (run.run_dir / "record.json").write_text(json.dumps(record.as_dict(), indent=2, default=str))
            return 0 if record.status == "ok" else 1
    except RunCannotStart as e:
        print(f"error: {e}", flush=True)
        return 2
