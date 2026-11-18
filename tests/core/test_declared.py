from pathlib import Path

import pytest

from agent_core.contracts.errors import RunCannotStart
from agent_core.core.declared import resolve
from agent_core.core.functions import import_declared
from agent_core.helpers.mcp import McpServers

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
INSTANCE = FIXTURES / "instance"
SERVERS = {
    "tools": {"command": "python", "args": [str(FIXTURES / "servers" / "shell_server.py")]},
    "web": {"command": "python", "args": [str(FIXTURES / "servers" / "flaky_server.py")]},
}
NAMES = {"tools": "tools", "web": "web"}


async def test_the_declared_set_holds_functions_and_server_tools_by_name(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_CORE_RUN_DIR", str(tmp_path))
    functions = {t.name: t for t in import_declared(INSTANCE, {"count_words": "functions:count_words"})}
    servers = McpServers(SERVERS, {"AGENT_CORE_RUN_DIR": str(tmp_path)}, INSTANCE)
    try:
        declared = await resolve(functions, servers, NAMES)
        assert declared.functions == frozenset({"count_words"})
        assert declared.servers is servers
        assert {"count_words", "tools__shell", "tools__note", "web__fetch"} <= set(declared.specs)
        assert all(name == spec.name for name, spec in declared.specs.items())
    finally:
        await servers.close()


async def test_a_function_and_a_server_tool_of_one_name_stop_the_run_naming_both(tmp_path):
    functions = {t.name: t for t in import_declared(INSTANCE, {"tools__shell": "functions:count_words"})}
    servers = McpServers(SERVERS, {"AGENT_CORE_RUN_DIR": str(tmp_path)}, INSTANCE)
    with pytest.raises(RunCannotStart) as e:
        await resolve(functions, servers, NAMES)
    assert str(e.value) == (
        'instance.yaml: two tools are named "tools__shell": function functions:count_words and server "tools"'
    )


async def test_a_server_that_cannot_start_stops_the_run_naming_it():
    servers = McpServers({"web": {"command": "false"}}, {}, INSTANCE)
    with pytest.raises(RunCannotStart) as e:
        await resolve({}, servers, {"web": "web"})
    assert str(e.value) == 'tool server "web" could not be started: it closed the connection before answering'
