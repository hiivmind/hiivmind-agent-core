"""`AdapterServers`: tool servers reached through `langchain-mcp-adapters`, one adapter session per server for a run.

The first group drives the source directly, as `tests/helpers/test_mcp.py` drives Plan 1's helper; the second runs
sequences through the facade on the `langgraph` backend (the model is scripted) and looks at what the servers saw.
"""

import asyncio
import json
import os
import signal
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "conformance"))
import script_model  # noqa: E402, F401  (registers the `script` model provider)

import agent_core  # noqa: E402
from agent_core.backends.langgraph.mcp import AdapterServers  # noqa: E402
from agent_core.contracts.errors import RunCannotStart, ToolError, ToolServerError  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
INSTANCE = FIXTURES / "instance"
DECLARED = {
    "tools": {"command": "python", "args": [str(FIXTURES / "servers" / "shell_server.py")]},
    "web": {"command": "python", "args": [str(FIXTURES / "servers" / "flaky_server.py")]},
}


def tool_calls(run_dir: Path) -> list[dict]:
    """The calls the fixture servers recorded, as the servers' own processes wrote them."""
    file = run_dir / "tool_calls.jsonl"
    return [json.loads(line) for line in file.read_text().splitlines()] if file.exists() else []


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    directory = tmp_path / "run"
    directory.mkdir()
    monkeypatch.setenv("AGENT_CORE_RUN_DIR", str(directory))
    return directory


@pytest.fixture
async def servers(run_dir):
    source = AdapterServers(DECLARED, {"AGENT_CORE_INSTANCE": str(INSTANCE), "AGENT_CORE_RUN_DIR": str(run_dir)}, INSTANCE)
    yield source
    await source.close()


async def test_server_tools_are_named_with_the_server_in_front(servers):                 # TOOL-14
    names = {t.name for t in await servers.tools()}
    assert {"tools__shell", "tools__note", "web__note", "web__fetch"} <= names


async def test_a_servers_tool_keeps_its_description_and_schema(servers):
    specs = {t.name: t for t in await servers.tools()}
    assert specs["tools__shell"].description.startswith("Run a shell command")
    assert specs["tools__shell"].schema["required"] == ["command"]


async def test_a_call_returns_the_results_text(servers):
    assert await servers.call("web__note", {"text": "x"}, {}) == "noted on web"


async def test_one_session_is_held_for_every_call(servers, run_dir):                      # TOOL-15
    await servers.call("tools__shell", {"command": "echo one"}, {})
    await servers.call("tools__shell", {"command": "echo two"}, {})
    assert len({line["server_pid"] for line in tool_calls(run_dir) if line["tool"] == "shell"}) == 1


async def test_the_server_is_given_the_environment_it_is_handed(servers, run_dir):
    await servers.call("tools__note", {"text": "hello"}, {})
    assert (run_dir / "notes.txt").read_text() == "hello\n"


async def test_a_servers_own_error_is_a_tool_error_with_its_message(servers):             # TOOL-11a
    with pytest.raises(ToolError, match="no such key: missing"):
        await servers.call("tools__lookup", {"key": "missing"}, {})


async def test_a_server_that_dies_is_a_tool_server_error_and_the_next_call_opens_a_new_session(servers, run_dir):   # TOOL-11e, TOOL-15
    with pytest.raises(ToolServerError) as e:
        await servers.call("web__fetch", {"url": "https://example.org/a"}, {})
    assert (e.value.server, e.value.tool) == ("web", "fetch")
    assert str(e.value) == "tool server `web` did not answer the call to `fetch`: it stopped answering"
    (run_dir / "web.up").touch()
    assert await servers.call("web__fetch", {"url": "https://example.org/a"}, {}) == "fetched https://example.org/a"
    assert await servers.call("web__fetch", {"url": "https://example.org/b"}, {}) == "fetched https://example.org/b"
    fetches = [line for line in tool_calls(run_dir) if line["tool"] == "fetch"]
    assert fetches[0]["server_pid"] != fetches[1]["server_pid"] == fetches[2]["server_pid"]


async def test_calls_in_flight_when_the_server_dies_each_fail_with_tool_server_error(servers, run_dir):   # TOOL-11e
    results = await asyncio.gather(
        *(servers.call("web__fetch", {"url": f"https://example.org/{n}"}, {}) for n in range(4)), return_exceptions=True,
    )
    assert all(isinstance(r, ToolServerError) and (r.server, r.tool) == ("web", "fetch") for r in results), results


async def test_close_ends_the_server_processes(servers, run_dir):
    await servers.call("tools__shell", {"command": "echo one"}, {})
    [pid] = {line["server_pid"] for line in tool_calls(run_dir)}
    await servers.close()
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        await asyncio.sleep(0.1)
    pytest.fail(f"the server process {pid} is still running after close")


async def test_a_server_that_exits_mid_call_fails_the_one_call_in_flight(servers):        # TOOL-11e
    with pytest.raises(ToolServerError) as e:
        await asyncio.wait_for(servers.call("web__fetch", {"url": "https://example.org/a"}, {}), 30)
    assert (e.value.server, e.value.tool) == ("web", "fetch")


async def stalled(servers, server: str, tool: str, args: dict):
    """A call of `tool` that the SDK will never answer (the coroutine of its adapter tool is made to wait for ever), started and in flight."""
    session = servers._held[server].tools[tool]

    async def never(*a, **kw):
        await asyncio.Event().wait()

    session.coroutine = never
    call = asyncio.create_task(servers.call(f"{server}__{tool}", args, {}))
    await asyncio.sleep(0.2)
    assert not call.done()
    return call


async def test_a_connection_that_closes_under_a_call_the_sdk_never_answers_fails_it(servers, run_dir):   # TOOL-11e: EOF, one call
    await servers.call("web__note", {"text": "x"}, {})
    [pid] = {line["server_pid"] for line in tool_calls(run_dir)}
    call = await stalled(servers, "web", "note", {"text": "y"})
    os.kill(pid, signal.SIGKILL)   # the server ends: its output closes, with no answer to the call
    with pytest.raises(ToolServerError) as e:
        await asyncio.wait_for(call, 30)
    assert (e.value.server, e.value.tool) == ("web", "note")
    (run_dir / "web.up").touch()
    assert await servers.call("web__note", {"text": "z"}, {}) == "noted on web"   # the next call opens a new session
    assert len({line["server_pid"] for line in tool_calls(run_dir)}) == 2


async def test_a_holder_that_fails_fails_the_calls_waiting_on_its_session(servers):       # TOOL-11e: the session ends with an error
    await servers.call("web__note", {"text": "x"}, {})
    call = await stalled(servers, "web", "note", {"text": "y"})
    servers._held["web"].task.cancel()   # what the SDK does to a session when its transport fails under it
    with pytest.raises(ToolServerError):
        await asyncio.wait_for(call, 30)
    assert await servers.call("web__note", {"text": "z"}, {}) == "noted on web"


async def test_a_call_on_a_session_whose_server_went_while_idle_is_a_tool_server_error(servers, run_dir):   # TOOL-11e
    await servers.call("web__note", {"text": "x"}, {})
    [pid] = {line["server_pid"] for line in tool_calls(run_dir)}
    os.kill(pid, signal.SIGKILL)
    await asyncio.wait_for(servers._held["web"].lost.wait(), 30)
    with pytest.raises(ToolServerError):
        await servers.call("web__note", {"text": "y"}, {})
    assert await servers.call("web__note", {"text": "z"}, {}) == "noted on web"


@pytest.mark.parametrize("spec,message", [
    ({"command": "corpus-web"}, 'tool server "web" could not be started: no such command "corpus-web"'),
    ({"url": "http://127.0.0.1:9/mcp"}, 'tool server "web" could not be reached at http://127.0.0.1:9/mcp'),
    ({"command": "false"}, 'tool server "web" could not be started: it closed the connection before answering')])
async def test_a_server_that_cannot_be_started_says_why(spec, message):                   # TOOL-11c
    source = AdapterServers({"web": spec}, {}, INSTANCE)
    try:
        with pytest.raises(RunCannotStart) as e:
            await source.tools()
    finally:
        await source.close()
    assert str(e.value) == message


# --- through the facade ------------------------------------------------------------------------------------------------

EXIT = ["exit", {"outcome": "done", "outputs": {}}]


def node(name: str, tools: list[str], inputs: str = "{}") -> str:
    return (
        f"---\nname: {name}\ndescription: {name}\ninputs: {inputs}\noutputs: {{}}\nexits: [done, failed]\n"
        f"allowed-tools: [{', '.join(tools)}]\n---\n# {name}\n\n## Steps\n\n1. Do it, then EXIT `done`.\n"
    )


TOPOLOGY = """\
nodes:
  - {name: first, path: nodes/first.md}
  - {name: second, path: nodes/second.md}
  - {name: fetcher, path: nodes/fetcher.md}
exits:
  done: route
  failed: route
sequences:
  two:
    description: Two nodes that each note on the web server.
    start: first
    transitions:
      first: {done: second, failed: end}
      second: {done: end, failed: end}
  fan:
    description: Fetch a page for each name, at once.
    start: {fan_out: fetcher, over: urls, as: url, into: pages, max_concurrency: 3}
    transitions:
      fetcher: {done: end, failed: end}
"""


@pytest.fixture
def opened(tmp_path, monkeypatch):
    """`opened(scripts)`: an instance of three nodes over the flaky web server, on `langgraph` with the model scripted."""
    def make(scripts: dict[str, list]):
        root = tmp_path / "instance"
        (root / "nodes").mkdir(parents=True)
        web = {"command": "python", "args": [str(FIXTURES / "servers" / "flaky_server.py")]}
        (root / "instance.yaml").write_text(
            f"name: mcp\ncore: 0\nentry: topology.yaml\npolicy: POLICY.md\nbackend: langgraph\nservers:\n  web: {json.dumps(web)}\n"
        )
        (root / "POLICY.md").write_text("Do what the procedure says.\n")
        (root / "topology.yaml").write_text(TOPOLOGY)
        (root / "nodes" / "first.md").write_text(node("first", ["web__note"]))
        (root / "nodes" / "second.md").write_text(node("second", ["web__note"]))
        (root / "nodes" / "fetcher.md").write_text(node("fetcher", ["web__fetch"], "{url: the page}"))
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        for name, steps in scripts.items():
            (scripts_dir / f"{name}.json").write_text(json.dumps(steps))
        monkeypatch.setenv("AGENT_CORE_LANGGRAPH_MODEL", f"script:{scripts_dir}")
        return agent_core.open(root / "instance.yaml", backend="langgraph", runs=tmp_path / "runs")

    return make


def notes(count: int) -> list:
    return [["web__note", {"text": f"n{n}"}] for n in range(count)]


async def test_one_session_per_server_for_a_run(opened, tmp_path):                        # TOOL-15, Ruling P2-1
    h = opened({"first": [notes(3), notes(2), [EXIT]], "second": [notes(3), notes(2), [EXIT]]})
    try:
        first = await h.sequences.run("two", {}, run_id="one")
        assert first.end == "done", first.summary
        calls = tool_calls(tmp_path / "runs" / "one")
        assert [line["tool"] for line in calls] == ["note"] * 10
        assert len({line["server_pid"] for line in calls}) == 1   # one server process: it saw one `initialize`
        second = await h.sequences.run("two", {}, run_id="two")
        assert second.end == "done", second.summary
        again = tool_calls(tmp_path / "runs" / "two")
        assert len(again) == 10 and len({line["server_pid"] for line in again}) == 1
        assert {line["server_pid"] for line in again} != {line["server_pid"] for line in calls}   # a run holds its own (TOOL-15)
    finally:
        await h.close()


async def test_a_server_that_dies_mid_fan_out_fails_each_call_in_flight(opened, tmp_path):   # Review Focus 5, TOOL-11e, TOOL-15
    fetch = [[["web__fetch", {"url": "https://example.org/a"}]], [EXIT]]
    h = opened({"fetcher": fetch})
    try:
        urls = ["a", "b", "c"]
        result = await h.sequences.run("fan", {"urls": urls}, run_id="dies")
        assert result.end == "failed"
        assert result.facts["pages"] == []
        gone = "tool server `web` did not answer the call to `fetch`: it stopped answering"
        assert result.facts["pages_failures"] == [
            {"item": url, "outcome": "failed", "reason": f"ToolServerError: {gone}"} for url in urls
        ]
        assert result.record.failures == [{"node": "fetcher", "error": f"ToolServerError: {gone}"}] * 3   # naming the node and the server
        (tmp_path / "runs" / "back").mkdir(parents=True)
        (tmp_path / "runs" / "back" / "web.up").touch()   # the server is back: the next run connects again
        again = await h.sequences.run("fan", {"urls": ["a"]}, run_id="back")
        assert (again.end, again.facts["pages"]) == ("done", [{}])
    finally:
        await h.close()


async def test_servers_start_with_the_environment_they_are_given(tmp_path, monkeypatch):    # RP-1
    from agent_core.backends.langgraph import LangGraphBackend
    from agent_core.backends.langgraph.settings import LangGraphSettings

    env = {**os.environ, "AGENT_CORE_RUN_DIR": str(tmp_path), "SERVERS_PROBE": "as given"}
    monkeypatch.setenv("SERVERS_PROBE", "in the process")
    source = LangGraphBackend(LangGraphSettings(MODEL=f"script:{tmp_path}")).servers(
        {"shell": {"command": "python", "args": ["-m", "agent_tools.shell_server"]}}, tmp_path, env
    )
    try:
        assert isinstance(source, AdapterServers)
        ran = json.loads(await source.call("shell__run", {"command": "echo $SERVERS_PROBE"}, {}))
        assert ran["stdout"] == "as given\n"
    finally:
        await source.close()
