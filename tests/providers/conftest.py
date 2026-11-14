from pathlib import Path

import pytest

from agent_core.core.instance import load_instance
from agent_core.core.settings import load_settings
from agent_core.resources.folder import FolderResources
from agent_core.tools.function import FunctionSource
from agent_core.tools.mcp_server import McpServerSource

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "instance"


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    """The run's directory: the fixture servers and functions record their calls here."""
    directory = tmp_path / "run"
    directory.mkdir()
    monkeypatch.setenv("AGENT_CORE_RUN_DIR", str(directory))
    return directory


@pytest.fixture
def instance():
    return load_instance(FIXTURE / "instance.yaml", FolderResources(FIXTURE))


@pytest.fixture
def functions(instance, run_dir):
    settings = load_settings(instance, [FIXTURE / "config" / "alpha.yaml"])
    declared = {name: instance.functions[name] for name in ("count_words", "read_ledger", "locate")}
    return FunctionSource(declared, settings, FIXTURE)


@pytest.fixture
async def servers(instance, run_dir):
    env = {"AGENT_CORE_INSTANCE": str(FIXTURE), "AGENT_CORE_RUN_DIR": str(run_dir)}
    source = McpServerSource(instance.servers, env, FIXTURE)
    yield source
    await source.close()

