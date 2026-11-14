import json
import os
import shutil
import sys
import time
from pathlib import Path

import pytest

from agent_core.backends.scripted import ScriptedBackend
from agent_core.core.instance import load_instance
from agent_core.core.node_runner import NodeRunner
from agent_core.person.nobody import Nobody
from agent_core.resources.folder import FolderResources
from agent_core.tools.mcp_server import McpServerSource

SHELL = {"shell": {"command": sys.executable, "args": ["-m", "agent_tools.shell_server"]}}  # as an instance declares it


@pytest.fixture
async def shell(tmp_path):
    """The shell server, reached as an instance reaches it; no AGENT_CORE_INSTANCE is set."""
    env = {k: v for k, v in os.environ.items() if k != "AGENT_CORE_INSTANCE"}
    source = McpServerSource(SHELL, env, tmp_path)
    yield source
    await source.close()


@pytest.fixture
async def shell_in(tmp_path):
    """The shell server with AGENT_CORE_INSTANCE set to a directory other than the one the server starts in."""
    instance = tmp_path / "the-instance"
    instance.mkdir()
    source = McpServerSource(SHELL, {**os.environ, "AGENT_CORE_INSTANCE": str(instance)}, tmp_path)
    yield source, instance
    await source.close()


async def run(source, command, **extra):
    return json.loads(await source.call("shell__run", {"command": command, **extra}, {}))


async def test_the_server_offers_one_tool_named_shell__run(shell):
    specs = await shell.tools()
    assert [t.name for t in specs] == ["shell__run"]
    assert specs[0].schema["required"] == ["command"]


async def test_runs_a_command_as_the_user(shell):
    r = json.loads(await shell.call("shell__run", {"command": "echo $HOME && exit 3"}, {}))
    assert r["exit"] == 3 and r["stdout"].strip() == os.environ["HOME"]


async def test_the_result_has_exit_stdout_stderr_and_cut(shell):
    r = await run(shell, "echo out; echo err >&2")
    assert r == {"exit": 0, "stdout": "out\n", "stderr": "err\n", "cut": 0}


async def test_a_command_is_run_with_the_users_environment(shell):
    r = await run(shell, "echo $USER:$PATH")
    assert r["stdout"].strip() == f"{os.environ.get('USER', '')}:{os.environ['PATH']}"


async def test_commands_paths_and_files_are_not_restricted(shell, tmp_path):                 # TOOL-8
    outside = tmp_path / "outside.txt"
    r = await run(shell, f"echo hello > {outside} && cat /etc/hostname && rm {outside}")
    assert r["exit"] == 0 and not outside.exists() and r["stdout"].strip() == Path("/etc/hostname").read_text().strip()


async def test_a_very_large_output_is_cut_to_its_tail(shell):                               # Review Focus 5
    r = await run(shell, "python -c \"print('x' * 100000 + 'END')\"")
    assert len(r["stdout"]) <= 20000 and r["stdout"].rstrip().endswith("END") and r["cut"] >= 80000


async def test_each_stream_is_cut_to_its_own_last_20000_characters_and_cut_counts_both(shell):
    r = await run(shell, "python -c \"import sys; print('a' * 30000); print('b' * 50000, file=sys.stderr)\"")
    assert len(r["stdout"]) == 20000 and len(r["stderr"]) == 20000
    assert r["stdout"].rstrip("\n") == "a" * 19999 and r["stderr"].rstrip("\n") == "b" * 19999
    assert r["cut"] == (30001 - 20000) + (50001 - 20000)


async def test_an_output_within_the_limit_is_not_cut(shell):
    r = await run(shell, "python -c \"print('y' * 19999, end='')\"")
    assert len(r["stdout"]) == 19999 and r["cut"] == 0


async def test_runs_in_the_instance_directory(shell_in):
    source, instance = shell_in
    r = await run(source, "pwd")
    assert Path(r["stdout"].strip()).resolve() == instance.resolve()


async def test_runs_in_the_current_directory_when_no_instance_is_set(shell, tmp_path):
    r = await run(shell, "pwd")
    assert Path(r["stdout"].strip()).resolve() == tmp_path.resolve()


async def test_a_command_that_outlives_its_timeout_is_ended_and_says_so(shell):
    started = time.monotonic()
    r = await run(shell, "echo before; sleep 30; echo after", timeout=1)
    assert time.monotonic() - started < 15
    assert r["exit"] == -1 and "timed out" in r["stderr"]
    assert r["stdout"].strip() == "before"


async def test_a_timeout_ends_the_commands_children_too(shell, tmp_path):
    marker = tmp_path / "survived"
    r = await run(shell, f"(sleep 3; touch {marker}) & wait", timeout=1)
    assert r["exit"] == -1 and "timed out" in r["stderr"]
    time.sleep(4)
    assert not marker.exists()


async def test_a_failing_command_is_a_result_not_an_error(shell):
    r = await run(shell, "echo oops >&2; exit 7")
    assert r["exit"] == 7 and r["stderr"].strip() == "oops"


@pytest.fixture
def instance_with_shell(tmp_path):
    """A one-node instance that declares the shell server and a node that may call `shell__run`."""
    root = tmp_path / "loud-instance"
    (root / "skills" / "loud").mkdir(parents=True)
    (root / "instance.yaml").write_text(
        "name: loud\ncore: 0\nentry: topology.yaml\npolicy: POLICY.md\nbackend: scripted\n"
        f"servers:\n  shell: {{command: {sys.executable}, args: [-m, agent_tools.shell_server]}}\n"
    )
    (root / "POLICY.md").write_text("Follow the procedure.\n")
    (root / "topology.yaml").write_text(
        "nodes:\n  - {name: loud, path: skills/loud}\nexits:\n  done: route\n  failed: route\n"
    )
    (root / "skills" / "loud" / "SKILL.md").write_text(
        "---\nname: loud\ndescription: Run a command that prints a lot.\ninputs: {}\n"
        "outputs:\n  said: {type: string, description: what was seen}\nexits: [done, failed]\nallowed-tools: [shell__run]\n---\n"
        "# Loud\n\n## Steps\n\n1. CALL `shell__run` with `command` set to `loud`.\n2. EXIT `done` with output `said` set to `seen`.\n"
    )
    return root


async def test_a_node_run_carries_on_after_a_cut_shell_output_and_the_result_says_how_much(instance_with_shell):   # R10
    instance = load_instance(instance_with_shell / "instance.yaml", FolderResources(instance_with_shell))
    source = McpServerSource(
        instance.servers, {**os.environ, "AGENT_CORE_INSTANCE": str(instance_with_shell)}, instance_with_shell
    )
    seen = {}

    class Watching(ScriptedBackend):
        async def drive(self, brief, controller):
            seen["controller"] = controller
            return await super().drive(brief, controller)

    script = [
        [["shell__run", {"command": "python -c \"print('x' * 100000 + 'END')\""}]],
        [["exit", {"outcome": "done", "outputs": {"said": "seen"}}]],
    ]
    try:
        tools = {spec.name: (source, spec) for spec in await source.tools()}
        runner = NodeRunner(
            instance, None, tools, frozenset(), Nobody(), FolderResources(instance_with_shell), []
        )
        result = await runner.run("loud", {}, driver=Watching(script=script), label="loud#1")
    finally:
        await source.close()
    assert result["outcome"] == "done" and result["outputs"] == {"said": "seen"}  # the run went on past the cut output
    shown = json.loads(seen["controller"].run.record[0].result)  # what the model was shown
    assert shown["cut"] >= 80000 and len(shown["stdout"]) <= 20000 and shown["stdout"].rstrip().endswith("END")


@pytest.mark.skipif(shutil.which("npx") is None, reason="npx is not installed; the reference file server is run with it")
async def test_the_file_server_named_in_the_readme_starts_and_reads_a_file(tmp_path):
    (tmp_path / "note.txt").write_text("hello from a file")
    files = McpServerSource(
        {"files": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", str(tmp_path)]}},
        dict(os.environ),
        tmp_path,
    )
    try:
        names = {t.name for t in await files.tools()}
        assert {
            "files__read_text_file", "files__write_file", "files__edit_file", "files__search_files", "files__list_directory",
        } <= names
        assert "hello from a file" in await files.call("files__read_text_file", {"path": str(tmp_path / "note.txt")}, {})
    finally:
        await files.close()
