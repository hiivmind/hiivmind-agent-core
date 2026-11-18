from pathlib import Path

import pytest

from agent_core.helpers.mcp import McpServers

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
INSTANCE = FIXTURES / "instance"
DECLARED = {  # as the fixture instance's instance.yaml declares them
    "tools": {"command": "python", "args": [str(FIXTURES / "servers" / "shell_server.py")]},
    "web": {"command": "python", "args": [str(FIXTURES / "servers" / "flaky_server.py")]},
}


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    """The run's directory: the fixture servers record their calls here."""
    directory = tmp_path / "run"
    directory.mkdir()
    monkeypatch.setenv("AGENT_CORE_RUN_DIR", str(directory))
    return directory


@pytest.fixture
async def servers(run_dir):
    source = McpServers(DECLARED, {"AGENT_CORE_INSTANCE": str(INSTANCE), "AGENT_CORE_RUN_DIR": str(run_dir)}, INSTANCE)
    yield source
    await source.close()
