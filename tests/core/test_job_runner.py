import asyncio
import os
from pathlib import Path

import pytest
from records import function_calls, shell_commands

from agent_core.backends.scripted import ScriptedBackend
from agent_core.contracts import RunEnd
from agent_core.contracts.registry import REGISTERED_BACKENDS
from agent_core.core.job_runner import open_run
from agent_core.core.registry import UnknownBackend

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
ALPHA = FIXTURES / "instance" / "config" / "alpha.yaml"
INSTANCE = FIXTURES / "instance" / "instance.yaml"
OK_SCRIPTS = FIXTURES / "scripts" / "ok"
ECHO = ["providers: [providers/echo_source.py]", "sources: {echo: {provider: echo}}"]
RECORD_KEYS = {
    "job", "params", "settings_files", "backend", "attended", "start", "end", "status", "summary", "failures",
    "model_calls", "runs",
}


# --- through the command: the record and the exit code ---------------------------------------------------------------


def test_a_job_that_needs_no_model_exits_zero(job):                                       # criterion 1, JOB-10
    ran = job("nothing")
    code, record = ran
    assert code == 0 and record["status"] == "ok" and record["summary"] == "already current" and record["model_calls"] == 0
    assert shell_commands(ran.run_dir) == ["echo up-to-date"]      # the server was given AGENT_CORE_RUN_DIR and wrote there


def test_the_record_has_what_the_job_did(job):                                            # JOB-9a, SCOPE-7
    code, record = job("refresh_given", params={"CORPUS_NAME": "alpha"})
    assert code == 0 and set(record) == RECORD_KEYS
    assert (record["job"], record["status"], record["summary"]) == ("refresh_given", "ok", "refresh done")
    assert (record["params"], record["settings_files"]) == ({"CORPUS_NAME": "alpha"}, [str(ALPHA)])
    assert (record["backend"], record["attended"], record["failures"]) == ("scripted", False, [])
    assert record["start"] <= record["end"] and record["start"].endswith("+00:00")
    [note] = record["runs"]
    assert (note["label"], note["node"], note["model_calls"]) == ("refresh#1", "refresh", 4)
    assert record["model_calls"] == 4 and note["tools"][-1] == "tools__shell" and note["handover"] == []
    assert [source for source, _ in note["parts"]][-1] == "node file: skills/refresh/SKILL.md"


def test_a_script_that_raises_fails_the_job(job):                                          # JOB-9b
    code, record = job("stuck")
    assert code == 1 and record["status"] == "failed" and record["summary"].startswith("RuntimeError:")
    assert [f["reason"] for f in record["failures"]] == ["invalid_output"]
    assert record["failures"][0]["node"] == "stuck" and record["failures"][0]["outputs"] == {}


def test_a_failed_node_does_not_fail_the_job_by_itself(job):
    code, record = job("refresh_missing", case="missing")
    assert code == 0 and [f["reason"] for f in record["failures"]] == ["needs_input"]
    assert record["status"] == "ok" and record["summary"] == "needs attention: Which sources should I update?"


def test_two_nodes_at_once_each_from_fresh_facts(job):                                     # criterion 12, JOB-8
    code, record = job("both")
    assert code == 0 and len(record["runs"]) == 2 and {r["label"] for r in record["runs"]} == {"refresh#1", "refresh#2"}


def test_call_returns_a_functions_value_and_a_servers_text_as_json(job):                   # JOB-2
    ran = job("tally")   # `nothing` shows the server's JSON text parsed: it reads status["stdout"]
    code, record = ran
    assert record["summary"]["direct"] == {"words": 3}                                    # a function's own value
    assert record["summary"]["raised"] == "FileNotFoundError: no ledger named main"
    assert [c["args"] for c in function_calls(ran.run_dir, "count_words")][0] == {"text": "alpha beta gamma"}
    assert code == 0                                                                       # the ledger node's own `failed` is not the job's
    assert [f["node"] for f in record["failures"]] == ["ledger"]


def test_a_servers_text_that_is_not_json_stays_text_and_a_dead_server_is_reached_again(job):   # JOB-2, TOOL-15
    code, record = job("fetch_retry")
    summary = record["summary"]
    assert code == 0 and summary["first"] == 'ToolServerError: tool server "web" stopped answering during `fetch`'
    assert (summary["second"], summary["third"]) == ("fetched https://example.org/a", "fetched https://example.org/b")
    assert summary["notes"] == ["noted on web", "noted"]


def test_an_uncaught_tool_server_error_fails_the_job_and_names_node_and_server(job):       # criterion 22
    code, record = job("fetch_down")
    assert code == 1 and record["failures"] == [{"node": "fetcher", "error": 'ToolServerError: tool server "web" stopped answering during `fetch`'}]
    assert record["status"] == "failed" and record["summary"].startswith("ToolServerError:")


def test_param_and_settings_reach_the_script(job):                                         # SET-4, SET-6
    code, record = job("show_settings", params={"CORPUS_NAME": "zeta"})
    assert code == 0 and record["summary"] == {
        "name": "zeta",                                  # the parameter beats the settings file
        "path": "/tmp/spike-corpus-alpha",               # the settings file beats the instance's own
        "repo": "example/corpus-alpha",
        "prefix": "automated/refresh-base",              # the instance's own settings
    }
    assert record["params"] == {"CORPUS_NAME": "zeta"}


def test_a_tool_source_of_the_instances_own_is_opened_and_called(job):                    # SRC-1, REG-1
    code, record = job("echo", instance_with_lines=ECHO)
    assert code == 0 and record["summary"] == {"said": "hello"}


def test_after_a_provider_failure_the_record_is_written_and_every_tool_source_was_closed(job):   # R10
    ran = job("refresh_given", case="no_such_scripts", instance_with_lines=ECHO)
    code, record = ran
    assert code == 1 and record["status"] == "failed" and record["summary"].startswith("NodeRunError: refresh#1: FileNotFoundError")
    assert record["failures"] == [] and [r["label"] for r in record["runs"]] == ["refresh#1"]
    assert (ran.run_dir / "echo.closed").exists()                                          # the instance's own source


# --- in the process: the run itself ----------------------------------------------------------------------------------


class Recording:
    """A backend that says what it was given and stops."""

    def __init__(self, settings):
        self.briefs = []

    async def drive(self, brief, controller):
        self.briefs.append(brief)
        return RunEnd(by_controller=False, said="recorded")


class NoSettings:
    pass


@pytest.fixture
def scripted(monkeypatch):
    monkeypatch.setenv("AGENT_CORE_SCRIPTED_SCRIPTS", str(OK_SCRIPTS))


@pytest.fixture
def recording(monkeypatch):
    monkeypatch.setitem(REGISTERED_BACKENDS, "recording", (Recording, NoSettings))


async def test_run_node_takes_a_backend_name(scripted, recording, tmp_path):               # VERB-4b, REG-2
    async with open_run(INSTANCE, settings_files=[ALPHA], run_dir=tmp_path / "run") as run:
        named = await run.run_node("refresh", {"sources": "polars"}, backend="recording")
        default = await run.run_node("refresh", {"sources": "polars"})
        with pytest.raises(UnknownBackend, match="no backend `langgrph`; backends are: langgraph, recording, scripted"):
            await run.run_node("refresh", {"sources": "polars"}, backend="langgrph")
    assert named == {"outcome": "failed", "reason": "no_exit", "said": "recorded", "outputs": {}}
    assert default["outcome"] == "done"                                                    # the instance's own: `scripted`
    assert [n.label for n in run.record.notes] == ["refresh#1", "refresh#2"]


async def test_a_backend_given_to_open_run_is_the_default_and_the_instances_is_the_last_resort(scripted, recording, tmp_path):
    async with open_run(INSTANCE, settings_files=[ALPHA], run_dir=tmp_path / "run", backend="recording") as run:
        assert run.record.backend == "recording"
        assert (await run.run_node("refresh", {"sources": "polars"}))["said"] == "recorded"
        assert (await run.run_node("refresh", {"sources": "polars"}, backend="scripted"))["outcome"] == "done"
    async with open_run(INSTANCE, settings_files=[ALPHA], run_dir=tmp_path / "again") as run:
        assert run.record.backend == "scripted"


async def test_a_driver_may_be_given_for_one_run(scripted, tmp_path):
    async with open_run(INSTANCE, settings_files=[ALPHA], run_dir=tmp_path / "run") as run:
        result = await run.run_node("refresh", {"sources": "polars"}, driver=ScriptedBackend(script=[]))
    assert result["reason"] == "no_exit"


async def test_each_run_is_kept_in_the_store_under_its_label(scripted, tmp_path):          # STATE-4
    async with open_run(INSTANCE, settings_files=[ALPHA], run_dir=tmp_path / "run") as run:
        await asyncio.gather(
            run.run_node("refresh", {"sources": "polars"}), run.run_node("refresh", {"sources": "ibis"}),
        )
        assert run.store.load("refresh#3") is None
    first, second = run.store.load("refresh#1"), run.store.load("refresh#2")
    assert first["session"] == second["session"] == {"branch": "refresh/alpha"}            # each from its own facts
    assert (first["node"]["inputs"], second["node"]["inputs"]) == ({"sources": "polars"}, {"sources": "ibis"})


async def test_a_node_starts_from_fresh_facts_whatever_ran_before(scripted, tmp_path):     # JOB-4, JOB-8
    class Seeing:
        def __init__(self):
            self.briefs = []

        async def drive(self, brief, controller):
            self.briefs.append(brief)
            return await ScriptedBackend(script=[]).drive(brief, controller)

    seeing = Seeing()
    async with open_run(INSTANCE, settings_files=[ALPHA], run_dir=tmp_path / "run") as run:
        await run.run_node("refresh", {"sources": "polars"})                               # records branch refresh/alpha
        await run.run_node("refresh", {"sources": "ibis"}, driver=seeing)
    branch = [line for line in seeing.briefs[0].instructions.splitlines() if line.startswith("Branch:")]
    assert branch and "refresh/alpha" not in branch[0]


async def test_a_question_is_put_with_the_runs_label_and_its_inputs_values(tmp_path, monkeypatch):   # JOB-6, example 10
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "asker.json").write_text('[[["ask", {"question": "Which colour for polars?"}]]]')
    monkeypatch.setenv("AGENT_CORE_SCRIPTED_SCRIPTS", str(scripts))
    asked = []

    class Answering:
        async def tell(self, text):
            pass

        async def ask(self, question, label=""):
            asked.append((question, label))
            return "green"

    async with open_run(INSTANCE, settings_files=[ALPHA], run_dir=tmp_path / "run") as run:
        run.person = Answering()
        await run.run_node("asker", {"who": "polars"})
    assert asked == [("Which colour for polars?", "asker#1 polars")]
    assert [n.label for n in run.record.notes] == ["asker#1"]                              # the record's label has no values


async def test_call_names_the_tools_when_there_is_none_by_that_name(tmp_path):
    async with open_run(INSTANCE, settings_files=[ALPHA], run_dir=tmp_path / "run") as run:
        with pytest.raises(ValueError, match="no tool `shell`; the tools are: .*tools__shell"):
            await run.call("shell", {"command": "true"})


async def test_the_tool_servers_and_functions_get_the_instance_and_the_run_directory(tmp_path):   # R11
    before = {k: os.environ.get(k) for k in ("AGENT_CORE_INSTANCE", "AGENT_CORE_RUN_DIR")}
    async with open_run(INSTANCE, settings_files=[ALPHA], run_dir=tmp_path / "made" / "run") as run:
        await run.call("count_words", {"text": "a b"})
        out = await run.call("tools__shell", {"command": 'echo "$AGENT_CORE_INSTANCE"'})
        assert (tmp_path / "made" / "run").is_dir()                                       # created, parents too
    assert out["stdout"].strip() == str(INSTANCE.parent)
    assert [c["args"] for c in function_calls(tmp_path / "made" / "run", "count_words")] == [{"text": "a b"}]
    assert {k: os.environ.get(k) for k in before} == before                                # the process is as it was


async def test_every_tool_source_is_closed_when_the_body_raises(make_instance, tmp_path):
    yaml = make_instance(instance_with_lines=ECHO)
    with pytest.raises(RuntimeError, match="the script broke"):
        async with open_run(yaml, settings_files=[ALPHA], run_dir=tmp_path / "run"):
            raise RuntimeError("the script broke")
    assert (tmp_path / "run" / "echo.closed").exists()
