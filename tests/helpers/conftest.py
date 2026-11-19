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


@pytest.fixture
def port(tmp_path, monkeypatch):
    """`port(nodes=Nodes(), check=None, sequences=None, fragments=None, pause=0)`: a `WalkPort` over the sequences fixture."""
    from walking import make_port

    return lambda **options: make_port(tmp_path, monkeypatch, **options)


@pytest.fixture
def walk(port):
    """`await walk(name, facts, **options)`: walk a sequence of the sequences fixture; options as for `port`."""
    from agent_core.helpers.walk import walk_sequence

    async def run(name, facts=None, **options):
        return await walk_sequence(port(**options), name, dict(facts or {}))

    return run
