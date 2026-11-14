import asyncio
import json
from pathlib import Path

import pytest

from agent_core.contracts.errors import ToolError, ToolServerError
from agent_core.tools.mcp_server import McpServerSource

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "instance"


def tool_calls(run_dir: Path) -> list[dict]:
    """The calls the fixture servers recorded, as the servers' own processes wrote them."""
    file = run_dir / "tool_calls.jsonl"
    return [json.loads(line) for line in file.read_text().splitlines()] if file.exists() else []


async def test_server_tools_are_named_with_the_server_in_front(servers):                 # TOOL-14
    names = {t.name for t in await servers.tools()}
    assert {"tools__shell", "tools__note", "web__note", "web__fetch"} <= names


async def test_a_servers_tool_keeps_its_description_and_schema(servers):
    specs = {t.name: t for t in await servers.tools()}
    assert specs["tools__shell"].description.startswith("Run a shell command")
    assert specs["tools__shell"].schema["required"] == ["command"]


async def test_a_call_returns_the_results_text(servers):
    assert await servers.call("web__note", {"text": "x"}, {}) == "noted on web"


async def test_one_connection_is_held(servers, run_dir):                                  # TOOL-15
    await servers.call("tools__shell", {"command": "echo one"}, {})
    await servers.call("tools__shell", {"command": "echo two"}, {})
    assert len({line["server_pid"] for line in tool_calls(run_dir) if line["tool"] == "shell"}) == 1


async def test_the_server_is_given_the_environment_it_is_handed(servers, run_dir):
    await servers.call("tools__note", {"text": "hello"}, {})
    assert (run_dir / "notes.txt").read_text() == "hello\n"


async def test_a_servers_own_error_is_a_tool_error(servers):                              # TOOL-11a
    with pytest.raises(ToolError, match="no such key: missing"):
        await servers.call("tools__lookup", {"key": "missing"}, {})


async def test_a_server_that_dies_is_a_tool_server_error_and_the_next_call_connects_again(servers, run_dir):   # TOOL-11e, TOOL-15
    with pytest.raises(ToolServerError) as e:
        await servers.call("web__fetch", {"url": "https://example.org/a"}, {})
    assert str(e.value) == 'tool server "web" stopped answering during `fetch`'
    (run_dir / "web.up").touch()
    assert await servers.call("web__fetch", {"url": "https://example.org/a"}, {}) == "fetched https://example.org/a"


async def test_a_late_failure_on_a_replaced_connection_leaves_the_new_one_open(servers, run_dir):
    (run_dir / "web.up").touch()
    await servers.tools()
    old = servers._held["web"]
    entered, release, original = asyncio.Event(), asyncio.Event(), old.session.call_tool

    async def stalls_then_fails(name, args, *rest, **kw):
        if name != "note":
            return await original(name, args, *rest, **kw)
        entered.set()
        await release.wait()
        raise RuntimeError("the connection went away")

    old.session.call_tool = stalls_then_fails
    late = asyncio.create_task(servers.call("web__note", {"text": "late"}, {}))
    await entered.wait()

    (run_dir / "web.up").unlink()                      # the server dies in the next fetch: the old connection is dropped
    with pytest.raises(ToolServerError):
        await servers.call("web__fetch", {"url": "https://example.org/a"}, {})
    (run_dir / "web.up").touch()                       # the next call connects again
    await servers.call("web__fetch", {"url": "https://example.org/b"}, {})
    assert servers._held["web"] is not old

    release.set()                                      # now the old connection's call fails, late
    with pytest.raises(ToolServerError) as e:
        await late
    assert str(e.value) == 'tool server "web" stopped answering during `note`'

    await servers.call("web__fetch", {"url": "https://example.org/c"}, {})
    fetches = [line for line in tool_calls(run_dir) if line["tool"] == "fetch"]
    assert fetches[-1]["server_pid"] == fetches[-2]["server_pid"] != fetches[0]["server_pid"]


@pytest.mark.parametrize("spec,message", [
    ({"command": "corpus-web"}, 'tool server "web" could not be started: no such command "corpus-web"'),
    ({"url": "http://127.0.0.1:9/mcp"}, 'tool server "web" could not be reached at http://127.0.0.1:9/mcp'),
    ({"command": "false"}, 'tool server "web" could not be started: it closed the connection before answering')])
async def test_a_server_that_cannot_be_started_says_why(spec, message):                   # TOOL-11c
    with pytest.raises(ToolServerError) as e:
        await McpServerSource({"web": spec}, {}, FIXTURE).tools()
    assert str(e.value) == message
