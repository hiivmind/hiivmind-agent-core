"""A `WalkPort` for walking the sequences fixture without a model or a backend: node runs a test scripts."""

import dataclasses
import inspect
from pathlib import Path

from agent_core.contracts.unit import UnitResult
from agent_core.contracts.walk import StepRef, WalkPort
from agent_core.core.checks import unmet_check
from agent_core.core.instance import load_instance
from agent_core.contracts.loading import load_module

SEQUENCES = Path(__file__).resolve().parents[1] / "fixtures" / "sequences"
RESULTS = {
    "update-sources": {"outcome": "updated", "outputs": {"rescan_batches": ["b1", "b2", "b3"], "sources_updated": ["polars"]}},
    "scan": {"outcome": "done", "outputs": {"entries": ["e1"]}},
    "index": {"outcome": "done", "outputs": {"entries": ["e1", "e2"]}},
    "verify": {"outcome": "done", "outputs": {"drift": 0}},
    "publish": {"outcome": "published", "outputs": {"pr_url": "https://example.org/pr/1"}},
    "status": {"outcome": "stale", "outputs": {"refresh_needed": True}},
    "migrate": {"outcome": "done", "outputs": {"entry_count": 3}},
    "graph": {"outcome": "done", "outputs": {"result": "ok"}},
    "first": {"outcome": "done", "outputs": {"first_done": "yes"}},
    "wrap": {"outcome": "done", "outputs": {"wrapped": "yes"}},
    "close": {"outcome": "done", "outputs": {"closed": "yes"}},
}


class FolderSource:
    def __init__(self, root: Path):
        self.root = Path(root)

    def read(self, path: str) -> str:
        return (self.root / path).read_text()

    def exists(self, path: str) -> bool:
        return (self.root / path).exists()


class NoSteps:
    """`Steps` that run each step and keep nothing."""

    async def step(self, name, call):
        return await call()

    def reserve(self, count):
        return [self] * count

    async def run(self, name, call):
        return await call()


class Nodes:
    """A `run_step` that gives each node its result from `results`, and keeps (name, inputs, ref, intent) of each run.

    A result may be a function of the inputs, or a coroutine function of them; `_` in a keyword stands for `-`. A
    result is a dict `{"outcome", "outputs"}`, a `UnitResult`, or raised by the function.
    """

    def __init__(self, **results):
        self.results = {**RESULTS, **{k.replace("_", "-"): v for k, v in results.items()}}
        self.runs: list[tuple[str, dict, StepRef, str]] = []

    async def __call__(self, name, inputs, ref, intent) -> UnitResult:
        self.runs.append((name, dict(inputs), ref, intent))
        result = self.results[name]
        if callable(result):
            result = result(inputs)
            if inspect.isawaitable(result):
                result = await result
        if isinstance(result, UnitResult):
            return result
        return UnitResult(result["outcome"], result.get("outputs", {}), result.get("reason"))

    @property
    def names(self) -> list[str]:
        return [name for name, *_ in self.runs]

    @property
    def inputs(self) -> list[tuple[str, dict]]:
        return [(name, inputs) for name, inputs, *_ in self.runs]


def names(result: dict) -> list[str]:
    return [entry["name"] for entry in result["trail"]]


def make_port(tmp_path, monkeypatch, nodes=None, check=None, sequences=None, fragments=None, pause=0) -> WalkPort:
    """A port over the sequences fixture; `sequences` and `fragments` add or replace some. The checks and tools are the
    fixture's own, as functions of its `checks` module."""
    monkeypatch.setenv("AGENT_CORE_RUN_DIR", str(tmp_path))
    instance = load_instance(SEQUENCES / "instance.yaml", FolderSource(SEQUENCES))
    topology = dataclasses.replace(
        instance.topology,
        sequences={**instance.topology.sequences, **(sequences or {})},
        fragments={**instance.topology.fragments, **(fragments or {})},
    )
    module = load_module(SEQUENCES, "checks")
    functions = {name: getattr(module, path.partition(":")[2]) for name, path in instance.functions.items()}

    async def call(name, args, state):
        function = functions[name]
        given = {"state": state}
        return function(**args, **{n: given[n] for n in inspect.signature(function).parameters})

    async def call_tool(tool, args):
        return functions[tool](**args)

    async def real_check(checks, facts, owner):
        return await unmet_check(checks, facts, owner=owner, call=call, functions=frozenset(functions), fill=str)

    return WalkPort(topology, nodes or Nodes(), call_tool, check or real_check, NoSteps(), pause)
