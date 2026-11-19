"""The conformance suite: each test runs once for every backend the registry names, through the facade.

`harness(scripts, **options)` opens a harness on the conformance instance, on the backend the test is running for. A
backend is given its scripts through its own setting (`DELIVERY`), so a test says what the model does and not how a
backend is told. A test carries `@pytest.mark.feature("F<n>")`; for a backend whose matrix entry for that feature is
`divergent` the test is expected to fail, and for `not built` it is skipped. The hooks below tell the audit
(`tests/audit.py`) which tests passed.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from script_model import ScriptProvider  # registers the `script` model provider
from audit import DESELECTED, all_matrices, record

import agent_core
from agent_core.contracts.matrix import Feature
from agent_core.core.registry import BACKENDS

HERE = Path(__file__).resolve().parent
INSTANCE = HERE / "instance"


def deliver_scripted(scripts: dict[str, list], directory: Path) -> dict[str, str]:
    """The scripted backend plays `<node>.json` of the directory its setting SCRIPTS names."""
    directory.mkdir(parents=True, exist_ok=True)
    for node, steps in scripts.items():
        (directory / f"{node}.json").write_text(json.dumps(steps))
    return {"AGENT_CORE_SCRIPTED_SCRIPTS": str(directory)}


def deliver_langgraph(scripts: dict[str, list], directory: Path) -> dict[str, str]:
    """The LangGraph backend plays the scripts through the `script` model provider: `MODEL=script:<directory>`."""
    deliver_scripted(scripts, directory)
    return {"AGENT_CORE_LANGGRAPH_MODEL": f"script:{directory}"}


DELIVERY = {"scripted": deliver_scripted, "langgraph": deliver_langgraph}   # backend name -> how its scripts reach it: the environment its settings read


def pytest_generate_tests(metafunc):
    if "backend_name" in metafunc.fixturenames:
        metafunc.parametrize("backend_name", list(BACKENDS))


@pytest.fixture
def delivered(backend_name, tmp_path, monkeypatch):
    """`delivered(scripts)`: give the backend these scripts, for this process; returns the environment it was given."""
    given = 0

    def deliver(scripts: dict[str, list]) -> dict[str, str]:
        nonlocal given
        given += 1
        environment = DELIVERY[backend_name](scripts, tmp_path / f"scripts-{given}")
        for key, value in environment.items():
            monkeypatch.setenv(key, value)
        return environment

    return deliver


@pytest.fixture
async def harness(backend_name, delivered, tmp_path, monkeypatch):
    """`harness(scripts, provider=None, **options)`: a harness on the conformance instance. `options` are those of
    `agent_core.open`; `runs` defaults to a directory of the test's own. `provider`, for the LangGraph backend, is the
    model setting in place of `script:<directory>` (`"naming:big-model-7"`): a provider of the test's own then plays the
    scripts, and finds their directory in `ScriptProvider.directory`."""
    opened = []

    def make(scripts: dict[str, list], provider: str | None = None, **options):
        environment = delivered(scripts)
        if provider is not None:
            directory = environment["AGENT_CORE_LANGGRAPH_MODEL"].partition(":")[2]
            monkeypatch.setenv("AGENT_CORE_LANGGRAPH_MODEL", provider)
            monkeypatch.setattr(ScriptProvider, "directory", directory, raising=False)
        options = {"backend": backend_name, "runs": tmp_path / "runs", **options}
        opened.append(agent_core.open(INSTANCE / "instance.yaml", **options))
        return opened[-1]

    yield make
    for each in opened:
        await each.close()


@pytest.fixture
def elsewhere(backend_name, delivered, tmp_path):
    """`elsewhere(scripts, sequence, run_id, facts)`: run a sequence in a process of its own, with these scripts, and
    wait for it to end; returns the finished `subprocess.CompletedProcess`. Its runs directory is the harness's."""

    def run(scripts: dict[str, list], sequence: str, run_id: str, facts: dict | None = None):
        environment = delivered(scripts)
        command = [
            sys.executable, str(HERE / "elsewhere.py"), str(INSTANCE / "instance.yaml"), backend_name,
            str(tmp_path / "runs"), sequence, run_id, json.dumps(facts or {}),
        ]
        return subprocess.run(command, env={**os.environ, **environment}, capture_output=True, text=True, timeout=300)

    return run


# --- the matrix decides what each test is expected to do ---------------------------------------------------------------

KEYS: dict[str, list[tuple[str, str]]] = {}   # node id -> the (backend, feature) pairs the test stands for


def _conformance(item) -> bool:
    return item.path.is_relative_to(HERE)


def _features(item) -> list[str]:
    return [feature for mark in item.iter_markers("feature") for feature in mark.args]


def pytest_collection_modifyitems(items):
    matrices = None
    for item in items:
        if not _conformance(item):
            continue
        matrices = matrices or all_matrices()
        backend = item.callspec.params["backend_name"]
        KEYS[item.nodeid] = [(backend, feature) for feature in _features(item)]
        for feature in _features(item):
            entry = matrices[backend][Feature(feature)]
            if entry.state == "divergent":
                item.add_marker(pytest.mark.xfail(strict=True, reason=entry.means))
            elif entry.state == "not built":
                item.add_marker(pytest.mark.skip(reason=entry.means))


def pytest_deselected(items):
    DESELECTED.extend(item.nodeid for item in items if _conformance(item))


def pytest_runtest_logreport(report):
    """A test counts as run only when each phase was good (see `audit.record`): a skip never counts."""
    keys = KEYS.get(report.nodeid)
    if keys is not None:
        record(report, keys)
