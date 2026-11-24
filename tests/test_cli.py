"""`agent-core job` on the fixture instance: start-up mistakes, the exit codes, the run directory, a person at the terminal."""

import json
import os
import re
import subprocess
import sys

import pytest
from cli_support import ALPHA, ASK, ASK_ONE, FIXTURES, PLAIN, REPO, Jobs, read_record

from agent_core.cli import main


@pytest.fixture
def job(tmp_path):
    """`job(name, ...)` runs the command in a subprocess on the fixture instance, with `config/alpha.yaml` as settings
    (the instance needs `CORPUS_REPO`) and the `plain_run` and `ask_one` sequences added."""
    jobs = Jobs(tmp_path, "instance")

    def run(name="plain_run", *, scripts=None, settings=(ALPHA,), with_lines="", **options):
        return jobs(name, scripts={"plain": PLAIN, "asker": ASK, **(scripts or {})}, settings=settings,
                    with_lines=ASK_ONE + with_lines, **options)

    run.jobs = jobs
    return run




def one_line(ran, message):
    """The run could not start: exit 2, `message` the last line printed (a run id may come first), no record."""
    assert ran.code == 2 and ran.out.splitlines()[-1] == message and ran.record == {}


@pytest.mark.parametrize("args,instance_with,message", [
    (["--backend", "nope"], None, "error: no backend `nope`; backends are: langgraph, scripted"),
    ([], "missing: functions:no_such_function",
     'error: instance.yaml: tool "missing": cannot import functions:no_such_function: '
     "ImportError: the module has no function `no_such_function`"),
    ([], "tools__shell: functions:count_words",
     'error: instance.yaml: two tools are named "tools__shell": function functions:count_words and server "tools"')])
def test_a_run_that_cannot_start_exits_two_with_one_line(job, args, instance_with, message):    # TOOL-16, REG-2, JOB-17
    one_line(job(args=args, with_tool=instance_with), message)


def test_missing_settings_exit_two_and_name_the_field_not_a_value(job):                         # SET-3
    one_line(job(settings=()), "error: settings: missing or invalid: CORPUS_REPO")


def test_a_tool_server_that_cannot_be_started_exits_two(job):                                   # R11
    ran = job(replace=("web: {command: python,", "web: {command: no-such-command-xyz,"))
    one_line(ran, 'error: tool server "web" could not be started: no such command "no-such-command-xyz"')


def test_a_name_that_is_not_a_sequence_exits_2_listing_the_sequences(job):                      # JOB-14
    ran = job("no_such_sequence")
    one_line(ran, "error: no sequence `no_such_sequence`; the sequences are: ask_one, plain_run")


FROZEN = (
    "import sys; from datetime import datetime, timezone; import agent_core.cli as cli\n"
    "class Frozen:\n    @staticmethod\n    def now(tz=None):\n        return datetime(2026, 11, 14, 1, 2, 3, tzinfo=timezone.utc)\n"
    "cli.datetime = Frozen\nsys.exit(cli.main(sys.argv[1:]))\n"
)


def command_in_a_process(tmp_path, args, *, jobs=None, cwd=REPO, name="plain_run", program="import sys; from agent_core.cli import main; sys.exit(main(sys.argv[1:]))"):
    """`main(args)` in a process of its own, on a copy of the fixture instance with the `plain` script; returns the
    finished process and the instance's `instance.yaml`."""
    jobs = jobs or Jobs(tmp_path, "instance")
    yaml = jobs.instance(with_lines=ASK_ONE)
    environment = {**os.environ, "AGENT_CORE_SCRIPTED_SCRIPTS": str(jobs.scripts("x", {"plain": PLAIN}))}
    done = subprocess.run(
        [sys.executable, "-c", program, "job", str(yaml), name, "--settings", str(ALPHA), *args],
        capture_output=True, text=True, cwd=cwd, env=environment, stdin=subprocess.DEVNULL, timeout=300,
    )
    return done, yaml


def test_the_run_directory_defaults_to_runs_name_the_utc_start_and_a_suffix_in_the_instance(tmp_path):
    done, yaml = command_in_a_process(tmp_path, [])
    assert done.returncode == 0, done.stdout + done.stderr
    [made] = (yaml.parent / "runs").glob("plain_run-*")
    assert re.fullmatch(r"plain_run-\d{8}T\d{6}Z-[0-9a-f]{6}", made.name) and (made / "record.json").is_file()
    assert done.stdout == f"run {made.name}\n"                                                  # RESUME-1: printed first


def test_main_returns_the_exit_code_and_takes_the_arguments_of_the_command(tmp_path):
    run = tmp_path / "run"
    done, _ = command_in_a_process(tmp_path, [
        "--param", "CORPUS_NAME=zeta", "--param", "BRANCH_PREFIX=x=y", "--run-dir", str(run), "--backend", "scripted", "--no-ask"])
    record = read_record(run)
    assert done.returncode == 0 and done.stdout == "run run\n"
    assert record["params"] == {"CORPUS_NAME": "zeta", "BRANCH_PREFIX": "x=y"} and record["backend"] == "scripted"
    assert record["attended"] is False and record["run_id"] == "run" and record["end_state"] == "done"


@pytest.mark.parametrize("directory,run_id,record", [(".", "here", "here"), ("sub/run", "run", "here/sub/run")])
def test_a_relative_run_directory_is_resolved_before_its_id_and_parent_are_taken(tmp_path, directory, run_id, record):
    here = tmp_path / "here"
    here.mkdir()
    done, _ = command_in_a_process(tmp_path, ["--run-dir", directory], cwd=here)
    assert done.returncode == 0 and done.stdout == f"run {run_id}\n", done.stdout + done.stderr
    assert read_record(tmp_path / record)["run_id"] == run_id
    assert not list(here.glob("plain_run-*"))                                                   # no second, generated id


def test_a_resumed_step_writes_its_files_into_the_run_directory_asked_for(tmp_path):
    jobs = Jobs(tmp_path, "sequences", FIXTURES / "sequences" / "scripts" / "ok")
    crashed = jobs("refresh", env={"SEQ_CRASH": "verify"})
    assert crashed.code == 3
    output = tmp_path / "output"
    # the fixture's tool is a function: it writes where the environment says, which the test sets to the run's (Q5)
    done = jobs("refresh", args=["--resume", "run", "--run-dir", str(output)], env={"AGENT_CORE_RUN_DIR": str(output)})
    assert done.code == 0 and done.out.startswith("run run\n"), done.out
    assert read_record(output)["run_id"] == "run"
    resumed = [json.loads(line) for line in (output / "calls.jsonl").read_text().splitlines()]   # a tool of the resumed step wrote it
    assert [call["node"] for call in resumed] == ["verify", "publish"]   # the steps the resume ran, and none that finished
    assert [json.loads(line)["node"] for line in (crashed.run_dir / "calls.jsonl").read_text().splitlines()][-1] == "verify"   # the crash's own


@pytest.mark.parametrize("again", [["--resume", "first"], ["--rerun-from", "first:1"], []])
def test_a_name_that_is_not_a_sequence_exits_2_in_every_mode(tmp_path, again):
    jobs = Jobs(tmp_path, "instance")
    done, _ = command_in_a_process(tmp_path, ["--run-dir", str(tmp_path / "first")], jobs=jobs)
    assert done.returncode == 0
    done, _ = command_in_a_process(tmp_path, [*again, "--run-dir", str(tmp_path / "next")], jobs=jobs, name="nope")
    assert done.returncode == 2 and done.stdout.splitlines()[-1] == "error: no sequence `nope`; the sequences are: ask_one, plain_run"
    assert not (tmp_path / "next" / "record.json").exists()


def test_a_param_without_a_value_is_a_usage_error():
    with pytest.raises(SystemExit) as e:
        main(["job", str(FIXTURES / "instance" / "instance.yaml"), "plain_run", "--param", "CORPUS_NAME"])
    assert e.value.code == 2


def test_the_command_has_the_job_subcommand_only():
    with pytest.raises(SystemExit) as e:
        main(["run", str(FIXTURES / "instance" / "instance.yaml")])
    assert e.value.code == 2


def test_two_jobs_started_in_the_same_second_do_not_share_a_run_directory(tmp_path):   # review 14
    jobs = Jobs(tmp_path, "instance")
    for _ in range(2):
        done, yaml = command_in_a_process(tmp_path, [], jobs=jobs, program=FROZEN)
        assert done.returncode == 0, done.stdout + done.stderr
    assert len(list((yaml.parent / "runs").glob("plain_run-20261114T010203Z-*"))) == 2


# --- a person at a terminal -------------------------------------------------------------------------------------------


def at_a_terminal(job, *, typed, args=()):
    """Run `ask_one` with a pseudo-terminal as standard input, typing `typed` into it; its output and its record."""
    import pty

    command, environment, run_dir = job.jobs.command(
        "ask_one", args=["--input", "who=polars", *args], settings=(ALPHA,), with_lines=ASK_ONE,
        scripts={"plain": PLAIN, "asker": ASK},
    )
    master, slave = pty.openpty()
    child = subprocess.Popen(
        command, stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=REPO, env=environment
    )
    os.close(slave)
    os.write(master, (typed + "\n").encode())   # typed ahead: the terminal holds it until the run reads
    try:
        out, _ = child.communicate(timeout=300)
    finally:
        os.close(master)
    return out, read_record(run_dir)


def test_a_question_at_a_terminal_is_put_with_its_label_and_answered(job):                      # JOB-6, criterion 20
    out, record = at_a_terminal(job, typed="red")
    assert "[asker#1 polars] Which colour?" in out and record["failures"] == []
    assert record["attended"] is True and (record["end_state"], record["facts"]["colour"]) == ("done", "red")


def test_no_ask_returns_needs_input_even_at_a_terminal(job):
    out, record = at_a_terminal(job, typed="red", args=["--no-ask"])
    assert "[asker#1" not in out                                                               # nothing was put to the terminal
    assert record["attended"] is False and [f["reason"] for f in record["failures"]] == ["needs_input"]
    assert record["failures"][0]["question"] == "Which colour?"


# --- the instance's own files, and a start-up mistake -----------------------------------------------------------------

SIBLINGS = {
    "tools/sources.py": "KINDS = ['docs', 'api']\n",
    "tools/status.py": "from .sources import KINDS\n\n\ndef status(state):\n    \"\"\"Say which kinds there are.\"\"\"\n"
                       "    state['done_work'] = ','.join(KINDS)\n    return {'kinds': KINDS}\n",
}
KINDS_NODE = "---\nname: plain\ndescription: Say the kinds.\ninputs: {}\noutputs:\n  done_work: {type: string, description: the kinds}\n" \
             "exits: [done, failed]\nallowed-tools: [status]\n---\n# Plain\n\n## Steps\n\n1. CALL `status`.\n2. EXIT `done`.\n"


def test_an_instances_files_import_each_other_relatively_through_the_command(job, tmp_path):        # review 1, E9
    script = [[["status", {}]], [["exit", {"outcome": "done", "outputs": {"done_work": "docs,api"}}]]]
    command, environment, run_dir = job.jobs.command(
        "plain_run", settings=(ALPHA,), scripts={"plain": script}, with_tool="status: tools.status:status",
        with_lines=ASK_ONE, files={**SIBLINGS, "nodes/plain.md": KINDS_NODE},
    )
    done = subprocess.run(command, capture_output=True, text=True, cwd=tmp_path, env=environment, stdin=subprocess.DEVNULL, timeout=300)
    assert done.returncode == 0 and done.stdout == "run run\n", done.stdout + done.stderr
    assert read_record(run_dir)["facts"]["done_work"] == "docs,api"


def test_an_absolute_sibling_import_does_not_load(job):                                           # E9, RP-3
    absolute = {**SIBLINGS, "tools/status.py": SIBLINGS["tools/status.py"].replace("from .sources", "from tools.sources")}
    ran = job(with_tool="status: tools.status:status", files=absolute)
    assert ran.code == 2 and ran.out == (
        'error: instance.yaml: tool "status": cannot import tools.status:status: '
        "ModuleNotFoundError: No module named 'tools'\n"
    )


def test_a_tool_file_that_fails_to_import_says_why_and_exits_two(job):                          # review 1, 3
    ran = job(with_tool="status: tools.status:status", files={"tools/status.py": "from .nothing import X\n"})
    assert ran.code == 2 and ran.out.count("\n") == 1
    assert ran.out.startswith('error: instance.yaml: tool "status": cannot import tools.status:status: ModuleNotFoundError')
    assert "tools.nothing" in ran.out


def test_a_tool_file_with_a_syntax_error_names_the_tool_and_exits_two(job):                     # review 3
    ran = job(with_tool="status: tools.status:status", files={"tools/status.py": "def status(:\n"})
    assert ran.code == 2 and ran.out.count("\n") == 1 and "Traceback" not in ran.out
    assert ran.out.startswith('error: instance.yaml: tool "status": cannot import tools.status:status: SyntaxError')


@pytest.mark.parametrize("name", ["PUSHH", "corpus_repo"])
def test_an_unknown_param_stops_the_run_before_it_starts(job, name):                            # review 2
    one_line(job(params={name: "false"}), f"error: settings: no setting named `{name}`")


def test_a_param_of_an_instance_without_settings_is_unknown(job):
    ran = job(settings=(), params={"PUSH": "false"}, replace=(
        "settings:\n  class: settings.SpikeSettings\n  files: [config/base.yaml]\n  env_prefix: SPIKE_\n", ""))
    one_line(ran, "error: settings: no setting named `PUSH`")


def test_a_settings_file_that_does_not_exist_exits_two_with_one_line(job, tmp_path):            # review 3
    ran = job(settings=(tmp_path / "nope.yaml",))
    assert ran.code == 2 and ran.out.count("\n") == 1 and "Traceback" not in ran.out
    assert ran.out.startswith("error: settings: ") and "nope.yaml" in ran.out


def test_a_settings_file_that_is_not_yaml_exits_two_with_one_line(job, tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("a: [unclosed\nb: : :\n")
    ran = job(settings=(bad,))
    assert ran.code == 2 and ran.out.count("\n") == 1 and ran.out.startswith("error: settings: ")


@pytest.mark.parametrize("replacement,files,says", [
    ("settings.NoSuchClass", {}, "settings.class `settings.NoSuchClass`: "),
    ("nofile.SpikeSettings", {}, "settings.class `nofile.SpikeSettings`: FileNotFoundError"),
    ("settings.SpikeSettings", {"settings.py": "raise RuntimeError('boom')\n"}, "settings.class `settings.SpikeSettings`: RuntimeError: boom"),
])
def test_a_settings_class_that_cannot_be_loaded_exits_two_with_one_line(job, replacement, files, says):   # review 3
    ran = job(replace=("settings.SpikeSettings", replacement), files=files)
    assert ran.code == 2 and ran.out.count("\n") == 1 and "Traceback" not in ran.out
    assert ran.out.startswith("error: " + says), ran.out


def test_a_param_for_a_secret_setting_is_written_masked(job):                                   # review 7
    code, record = job(params={"GITHUB_TOKEN": "ghp_very_secret", "BRANCH_PREFIX": "mine"})
    assert code == 0 and record["params"] == {"GITHUB_TOKEN": "********", "BRANCH_PREFIX": "mine"}
    assert "ghp_very_secret" not in json.dumps(record)

