import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent_core.core.cli import main

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
ALPHA = str(FIXTURES / "instance" / "config" / "alpha.yaml")
INSTANCE = FIXTURES / "instance"
ECHO = ["providers: [providers/echo_source.py]", "sources: {echo: {provider: echo}}"]


@pytest.mark.parametrize("args,instance_with,message", [
    (["--backend", "langgrph"], None, "error: no backend `langgrph`; backends are: langgraph, scripted"),
    ([], "missing: functions:no_such_function",
     'error: instance.yaml: tool "missing": cannot import functions:no_such_function: '
     "ImportError: the module has no function `no_such_function`"),
    ([], "tools__shell: functions:count_words",
     'error: instance.yaml: two tools are named "tools__shell": function functions:count_words and server "tools"')])
def test_a_run_that_cannot_start_exits_two_with_one_line(job, args, instance_with, message):    # TOOL-16, REG-2
    ran = job("nothing", args=args, instance_with=instance_with)
    assert ran.code == 2 and ran.out == message + "\n" and ran.record == {}                       # no job ran: no record


def test_a_source_the_instance_names_but_no_provider_registers_exits_two(job):                 # R5
    ran = job("echo", instance_with_lines=["providers: [providers/echo_source.py]", "sources: {echo: {provider: ehco}}"])
    assert ran.code == 2
    assert ran.out == 'error: instance.yaml: source "echo": no tool source `ehco`; tool sources are: echo\n'


def test_a_source_and_a_function_that_name_a_tool_alike_exit_two(job):
    ran = job("echo", instance_with="echo__say: functions:count_words", instance_with_lines=ECHO)
    assert ran.code == 2
    assert ran.out == 'error: instance.yaml: two tools are named "echo__say": function functions:count_words and source "echo"\n'


def test_missing_settings_exit_two_and_name_the_field_not_a_value(job):                        # SET-3
    ran = job("nothing", settings=())
    assert ran.code == 2 and ran.out == "error: settings: missing or invalid: CORPUS_REPO\n"


def test_a_tool_server_that_cannot_be_started_exits_two(job):                                  # R11
    ran = job("nothing", instance_replace=("web: {command: python,", "web: {command: no-such-command-xyz,"))
    assert ran.code == 2 and ran.out == 'error: tool server "web" could not be started: no such command "no-such-command-xyz"\n'


def test_a_job_the_instance_does_not_have_exits_two(job):                                      # R11
    ran = job("no_such_job")
    assert ran.code == 2 and ran.record == {}
    assert ran.out.startswith("error: no sequence or job script `no_such_job`; the sequences are: none; the job scripts are: ")


def test_a_job_file_without_main_exits_two(make_instance, capsys, tmp_path):                   # R11
    yaml = make_instance(instance_with_lines=["# edited"])
    (yaml.parent / "jobs" / "no_main.py").write_text("def other(job): ...\n")
    code = main(["job", str(yaml), "no_main", "--settings", ALPHA, "--run-dir", str(tmp_path / "run")])
    assert code == 2 and capsys.readouterr().out == f"error: no job `no_main` in {yaml.parent}/jobs/\n"


def test_a_job_file_that_raises_when_loaded_fails_the_job(make_instance, capsys, tmp_path):
    yaml = make_instance(instance_with_lines=["# edited"])
    (yaml.parent / "jobs" / "broken.py").write_text("raise RuntimeError('cannot even start')\n")
    code = main(["job", str(yaml), "broken", "--settings", ALPHA, "--run-dir", str(tmp_path / "run")])
    assert code == 1 and "RuntimeError: cannot even start" in (tmp_path / "run" / "record.json").read_text()


def test_the_run_directory_defaults_to_runs_job_the_utc_start_and_a_suffix_in_the_instance(make_instance, capsys):
    yaml = make_instance(instance_with_lines=["# edited"])
    assert main(["job", str(yaml), "nothing", "--settings", ALPHA]) == 0
    [made] = (yaml.parent / "runs").iterdir()
    assert re.fullmatch(r"nothing-\d{8}T\d{6}Z-[0-9a-f]{6}", made.name) and (made / "record.json").is_file()
    assert capsys.readouterr().out == ""


def test_main_returns_the_exit_code_and_takes_the_arguments_of_the_command(make_instance, tmp_path):
    yaml = make_instance(instance_with_lines=["# edited"])
    run = str(tmp_path / "run")
    assert main(["job", str(yaml), "show_settings", "--settings", ALPHA, "--param", "CORPUS_NAME=zeta", "--param", "BRANCH_PREFIX=x=y",
                 "--run-dir", run, "--backend", "scripted", "--no-ask"]) == 0
    record = json.loads((tmp_path / "run" / "record.json").read_text())
    assert record["params"] == {"CORPUS_NAME": "zeta", "BRANCH_PREFIX": "x=y"} and record["backend"] == "scripted"
    assert record["summary"]["prefix"] == "x=y" and record["attended"] is False


def test_a_param_without_a_value_is_a_usage_error():
    with pytest.raises(SystemExit) as e:
        main(["job", str(INSTANCE / "instance.yaml"), "nothing", "--param", "CORPUS_NAME"])
    assert e.value.code == 2


def test_the_command_has_the_job_subcommand_only():
    with pytest.raises(SystemExit) as e:
        main(["run", str(INSTANCE / "instance.yaml")])
    assert e.value.code == 2


# --- a person at a terminal -------------------------------------------------------------------------------------------


def test_a_question_at_a_terminal_is_put_with_its_label_and_answered(pty_job):             # criterion 20
    out, record = pty_job("refresh_missing", typed="polars")
    assert "[refresh#1] Which sources should I update?" in out and record["failures"] == []
    assert record["attended"] is True and [r["outcome"] for r in record["summary"]["returned"]] == ["done"]


def test_no_ask_returns_needs_input_even_at_a_terminal(pty_job):
    out, record = pty_job("refresh_missing", typed="polars", args=["--no-ask"])
    assert "[refresh#1]" not in out                                                       # nothing was put to the terminal
    assert record["attended"] is False and [f["reason"] for f in record["failures"]] == ["needs_input"]
    assert record["failures"][0]["question"] == "Which sources should I update?"


def test_two_jobs_started_in_the_same_second_do_not_share_a_run_directory(make_instance, monkeypatch):    # review 14
    class Frozen:
        @staticmethod
        def now(tz=None):
            return datetime(2026, 11, 14, 1, 2, 3, tzinfo=timezone.utc)

    monkeypatch.setattr("agent_core.core.cli.datetime", Frozen)
    yaml = make_instance(instance_with_lines=["# edited"])
    for _ in range(2):
        assert main(["job", str(yaml), "nothing", "--settings", ALPHA]) == 0
    assert len(list((yaml.parent / "runs").iterdir())) == 2


# --- the instance's own files, and a startup mistake ----------------------------------------------------------------

SIBLINGS = {
    "tools/sources.py": "KINDS = ['docs', 'api']\n",
    "tools/status.py": "from tools.sources import KINDS\n\n\ndef status():\n    \"\"\"Say which kinds there are.\"\"\"\n    return {'kinds': KINDS}\n",
    "jobs/kinds.py": "from tools.sources import KINDS\n\n\nasync def main(job):\n    return [await job.call('status', {}), KINDS]\n",
}


def test_an_instances_files_import_each_other_by_name_through_the_command(make_instance, tmp_path):   # review 1
    yaml = make_instance(instance_with="status: tools.status:status", files=SIBLINGS)
    run = tmp_path / "run"
    done = subprocess.run(
        [sys.executable, "-m", "agent_core.core.cli", "job", str(yaml), "kinds", "--settings", ALPHA, "--run-dir", str(run)],
        capture_output=True, text=True, cwd=tmp_path, stdin=subprocess.DEVNULL, timeout=120,
    )
    assert done.returncode == 0 and done.stdout == "", done.stdout
    assert json.loads((run / "record.json").read_text())["summary"] == [{"kinds": ["docs", "api"]}, ["docs", "api"]]


def test_a_tool_file_that_fails_to_import_says_why_and_exits_two(job):                          # review 1, 3
    ran = job("nothing", instance_with="status: tools.status:status", files={"tools/status.py": "from tools.nothing import X\n"})
    assert ran.code == 2 and ran.out.count("\n") == 1
    assert ran.out.startswith('error: instance.yaml: tool "status": cannot import tools.status:status: ModuleNotFoundError')
    assert "tools.nothing" in ran.out


def test_a_tool_file_with_a_syntax_error_names_the_tool_and_exits_two(job):                     # review 3
    ran = job("nothing", instance_with="status: tools.status:status", files={"tools/status.py": "def status(:\n"})
    assert ran.code == 2 and ran.out.count("\n") == 1 and "Traceback" not in ran.out
    assert ran.out.startswith('error: instance.yaml: tool "status": cannot import tools.status:status: SyntaxError')


@pytest.mark.parametrize("name", ["PUSHH", "corpus_repo"])
def test_an_unknown_param_stops_the_run_before_the_job_starts(job, name):                       # review 2
    ran = job("nothing", params={name: "false"})
    assert ran.code == 2 and ran.out == f"error: settings: no setting named `{name}`\n" and ran.record == {}


def test_a_param_of_an_instance_without_settings_is_unknown(job):
    ran = job("nothing", settings=(), params={"PUSH": "false"}, instance_replace=(
        "settings:\n  class: settings.SpikeSettings\n  files: [config/base.yaml]\n  env_prefix: SPIKE_\n", ""))
    assert ran.code == 2 and ran.out == "error: settings: no setting named `PUSH`\n"


def test_a_settings_file_that_does_not_exist_exits_two_with_one_line(job, tmp_path):            # review 3
    ran = job("nothing", settings=(tmp_path / "nope.yaml",))
    assert ran.code == 2 and ran.out.count("\n") == 1 and "Traceback" not in ran.out
    assert ran.out.startswith("error: settings: ") and "nope.yaml" in ran.out


def test_a_settings_file_that_is_not_yaml_exits_two_with_one_line(job, tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("a: [unclosed\nb: : :\n")
    ran = job("nothing", settings=(bad,))
    assert ran.code == 2 and ran.out.count("\n") == 1 and ran.out.startswith("error: settings: ")


@pytest.mark.parametrize("replacement,files,says", [
    ("settings.NoSuchClass", {}, "settings.class `settings.NoSuchClass`: "),
    ("nofile.SpikeSettings", {}, "settings.class `nofile.SpikeSettings`: FileNotFoundError"),
    ("settings.SpikeSettings", {"settings.py": "raise RuntimeError('boom')\n"}, "settings.class `settings.SpikeSettings`: RuntimeError: boom"),
])
def test_a_settings_class_that_cannot_be_loaded_exits_two_with_one_line(job, replacement, files, says):   # review 3
    ran = job("nothing", instance_replace=("settings.SpikeSettings", replacement), files=files)
    assert ran.code == 2 and ran.out.count("\n") == 1 and "Traceback" not in ran.out
    assert ran.out.startswith("error: " + says), ran.out


def test_a_tool_source_that_cannot_be_made_exits_two_naming_the_source(job):                    # review 3
    broken = (
        "from agent_core.contracts.registry import register\n\n\n@register('tool_source', 'broken')\n"
        "class Broken:\n    def __init__(self, key, entry, root):\n        raise KeyError('endpoint')\n"
    )
    ran = job(
        "nothing", instance_with_lines=["providers: [providers/broken.py]", "sources: {odd: {provider: broken}}"],
        files={"providers/broken.py": broken},
    )
    assert ran.code == 2 and ran.out == "error: instance.yaml: source \"odd\": KeyError: 'endpoint'\n"


def test_a_param_for_a_secret_setting_is_written_masked(job):                                   # review 7
    code, record = job("nothing", params={"GITHUB_TOKEN": "ghp_very_secret", "BRANCH_PREFIX": "mine"})
    assert code == 0 and record["params"] == {"GITHUB_TOKEN": "********", "BRANCH_PREFIX": "mine"}
    assert "ghp_very_secret" not in json.dumps(record)
