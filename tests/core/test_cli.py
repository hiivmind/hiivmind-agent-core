import json
import re
from pathlib import Path

import pytest

from agent_core.core.cli import main

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
ALPHA = str(FIXTURES / "instance" / "config" / "alpha.yaml")
INSTANCE = FIXTURES / "instance"
ECHO = ["providers: [providers/echo_source.py]", "sources: {echo: {provider: echo}}"]


@pytest.mark.parametrize("args,instance_with,message", [
    (["--backend", "langgrph"], None, "error: no backend `langgrph`; backends are: langgraph, scripted"),
    ([], "missing: functions:no_such_function", 'error: instance.yaml: tool "missing": cannot import functions:no_such_function'),
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
    assert ran.code == 2 and ran.out == f"error: no job `no_such_job` in {INSTANCE}/jobs/\n" and ran.record == {}


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


def test_the_run_directory_defaults_to_runs_job_and_the_utc_start_in_the_instance(make_instance, capsys):
    yaml = make_instance(instance_with_lines=["# edited"])
    assert main(["job", str(yaml), "nothing", "--settings", ALPHA]) == 0
    [made] = (yaml.parent / "runs").iterdir()
    assert re.fullmatch(r"nothing-\d{8}T\d{6}Z", made.name) and (made / "record.json").is_file()
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
    assert record["attended"] is True and record["summary"] == "refresh done"


def test_no_ask_returns_needs_input_even_at_a_terminal(pty_job):
    out, record = pty_job("refresh_missing", typed="polars", args=["--no-ask"])
    assert "[refresh#1]" not in out                                                       # nothing was put to the terminal
    assert record["attended"] is False and [f["reason"] for f in record["failures"]] == ["needs_input"]
    assert record["failures"][0]["question"] == "Which sources should I update?"
