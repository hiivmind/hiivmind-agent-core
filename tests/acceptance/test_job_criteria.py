"""The job acceptance suite: `agent-core job` with the LangGraph backend and a real model, on the fixture instance.

Criteria covered (requirements §6): 1, 3 (a) to (g), 12, 14 (job), 17 (job), 20, 21 (job), 22 (job). Each test is a job
probe of the spike (`hiivmind-agent-core-spike/probes/run.py`, `j0` to `j20`), named by its number, with its assertions
kept. Three things differ from the spike: what each `run_node` returned is read from the job's summary (each fixture job
returns `{"returned": [...]}`); the requests, and the answers to them, are read from a trace written at the provider's
HTTP client (`conftest.py`, `traced_cli.py`) and not from a log kept by the harness; and a probe that depended on the
harness reporting `corrections` or `carried` in a result reads them from the calls on the wire (the core's results hold
neither). A check that depends on the model choosing a wrong first move (`j3`, `j16`, the first check of `j20`) is
reported as skipped, "not exercised", when it did not.

Left out, and why:
- `p1` (settings, templates), `p2` (the model identifier): they call no job and are step 1's own rules, tested with no
  model in `tests/core`; the identifier is the suite's setting.
- `p3`, `p3b`, `p4`, `p4b`, `p6`, `p7`, `p8`, `p9`, `p10`, `p11`, `p12`, `p13`: session probes (pause and resume, routing,
  diversions, keeping a long session short, forged calls in a session, menus): step 2's.
- The session halves of `j13` (a session started in a node whose check cannot run; a forged ENTER), `j14` (a function tool
  in a session, a forged call), `j15` (a server's error and the recording of a function's writes in a session), `j16` (an
  output recorded in a session, and a fact of an earlier node), `j18` (a server that is down in a session; the user's
  reply) and `j20` (a check's writes in a session; a refused ENTER): step 2's.
- `j6b`: it records what a model does when no output can satisfy a schema and it is not told to persist, as an
  observation. It has no assertion and tests no criterion or requirement.
- `x1`: it compares the node file a session process loaded with the one a job process loaded (criterion 5): step 2's.
- Nothing within a ported probe is dropped: `j1`'s check that no routing or diversion rules and no list of nodes were sent is
  kept, because it reads the job's own instructions (ENGINE.md offers a job its five verbs and no more).
Added to the spike's checks: `j6` also checks that a node with an empty `allowed-tools` was offered the five verbs and no
tool (criterion 14, second sentence).
"""

import os
import re
import select
import time

import pytest

pytestmark = pytest.mark.model

QUESTION = "Which sources should I update?"
JOB_VERBS = {"exit", "ask", "state_set", "state_get", "load"}
REJECTED = "the outputs do not match the node's output schema"
CHECK = "test -f config.yaml && echo present || echo missing"
READY_CHECK = "test -f alpha.ready"
NOT_READY = "The corpus alpha is not ready: there is no alpha.ready file."
WHERE = "/tmp/spike-corpus-alpha/polars"
FAULT = 'tool server "web" stopped answering during `fetch`'


def no_saved_session(ran) -> None:
    files = ran.files()
    assert not any("sqlite" in f or f.startswith("session_") for f in files), files


def rejected(calls) -> list:
    """The `exit` calls the harness sent back for an output of the wrong shape."""
    return [c for c in calls if c.name == "exit" and (c.result or "").startswith(REJECTED)]


# --- criterion 1: a job that needs no model --------------------------------------------------------------------------


def test_j0_a_job_that_needs_no_model_finishes_without_starting_it(accept):               # criterion 1, JOB-10
    ran = accept.run("nothing")
    record = ran.record
    assert ran.code == 0 and record["status"] == "ok" and record["summary"] == "already current"
    assert record["model_calls"] == 0, record
    assert ran.shell_commands() == ["echo up-to-date"]    # the script's `call` reached the MCP shell tool
    no_saved_session(ran)


def test_j1_a_node_with_its_input_finishes_with_its_outputs(accept):                      # criterion 3, JOB-4, NODE-6
    ran = accept.run("refresh_given")
    r, reqs = ran.first, ran.trace
    assert ran.code == 0 and r["outcome"] == "done" and r["outputs"]["branch"] == "refresh/alpha"
    assert "polars" in str(r["outputs"]["sources_updated"]), r
    # It asked nothing: both steps ran and no question was raised.
    assert r.get("reason") is None and ran.shell_commands() == ["echo checked alpha", "echo updating polars"]
    assert reqs and "Sources to update: polars." in reqs[0]["system"]    # the first request already showed the input
    assert all("## Routing" not in q["system"] and "## Diversions" not in q["system"]
               and "# Nodes of this instance" not in q["system"] for q in reqs)
    assert all(set(q["tools"]) == JOB_VERBS | {"tools__shell"} for q in reqs), reqs[0]["tools"]
    no_saved_session(ran)


# --- criterion 3: the failure paths ------------------------------------------------------------------------------------


def test_j2_a_question_with_nobody_there_ends_the_node_as_needs_input(accept):             # criterion 3 (a)
    ran = accept.run("refresh_missing")
    r, record = ran.first, ran.record
    assert r["outcome"] == "failed" and r["reason"] == "needs_input" and r["question"] == QUESTION, r
    assert ran.shell_commands() == ["echo checked alpha"]    # the node stopped at the question: later steps did not run
    # The script carried on and the run record lists the failure.
    assert ran.code == 0 and record["status"] == "ok"
    assert [f["reason"] for f in record["failures"]] == ["needs_input"]


def test_j3_a_first_output_of_the_wrong_shape_is_corrected_once(accept):                   # criterion 3 (b), JOB-7b
    ran = accept.run("shape")
    r, sent_back = ran.first, rejected(ran.calls_of("shape"))
    if not sent_back:
        pytest.skip("not exercised: the model's first output had the right shape")
    assert r["outcome"] == "done" and len(sent_back) == 1 and r["outputs"] == {"count": 3}, r


def test_j4_two_outputs_of_the_wrong_shape_end_as_invalid_output(accept):                   # criterion 3 (c), JOB-7b
    ran = accept.run("stuck")
    record = ran.record
    r = record["failures"][0] if record.get("failures") else {}
    exits = [c for c in ran.calls_of("stuck") if c.name == "exit"]
    # Two outputs of the wrong shape: the first was sent back once, the second ended the run.
    assert r.get("outcome") == "failed" and r.get("reason") == "invalid_output" and bool(r.get("errors")), r
    assert len(exits) == 2 and (exits[0].result or "").startswith(REJECTED), [(c.input, c.result) for c in exits]
    # The script failed the job: non-zero exit and a failed run record.
    assert ran.code == 1 and record["status"] == "failed"
    assert [f["reason"] for f in record["failures"]] == ["invalid_output"]


def test_j5_two_node_runs_at_once_each_from_fresh_facts(accept):                           # criterion 12, JOB-8
    ran = accept.run("both")
    assert ran.code == 0 and len(ran.returned) == 2
    for name, r in zip(("polars", "ibis"), ran.returned):    # gathered in this order: each result is its own
        assert r["outcome"] == "done" and name in str(r["outputs"]["sources_updated"]), r
        assert r["outputs"]["branch"] == "refresh/alpha", r
    reqs = ran.trace
    spans = {}
    for q in reqs:    # a run is told apart by its input: the procedure shows it
        key = next(line for line in q["system"].splitlines() if line.startswith("Sources to update:"))
        first, last = spans.get(key, (q["ts"], q["ts"]))
        spans[key] = (min(first, q["ts"]), max(last, q["ts"]))
    windows = sorted(spans.values())
    assert len(windows) == 2 and windows[1][0] < windows[0][1], spans    # the two runs overlapped in time
    firsts = {key: next(q["system"] for q in reqs if key in q["system"]) for key in spans}
    assert len(firsts) == 2 and all("Branch: not set." in s for s in firsts.values())    # each from fresh facts
    assert sorted(ran.shell_commands()) == ["echo checked alpha", "echo checked alpha", "echo updating ibis",
                                            "echo updating polars"]
    no_saved_session(ran)


def test_j6_a_node_that_stops_without_exit_is_no_exit(accept):                             # criterion 3 (d), JOB-12
    ran = accept.run("silent")
    r = ran.first
    assert r["outcome"] == "failed" and r["reason"] == "no_exit" and r["said"].strip(), r
    assert [f["reason"] for f in ran.record["failures"]] == ["no_exit"]
    # A node with an empty `allowed-tools` was offered the verbs and no tool (criterion 14).
    assert ran.trace and all(set(q["tools"]) == JOB_VERBS for q in ran.trace), [q["tools"] for q in ran.trace]


def test_j7_a_nodes_own_failed_exit_keeps_its_reason_in_the_record(accept):                # criterion 3 (e), JOB-13
    ran = accept.run("giveup")
    r = ran.first
    reason = r["outputs"].get("reason")
    assert r["outcome"] == "failed" and isinstance(reason, str) and reason, r
    assert [f["outputs"].get("reason") for f in ran.record["failures"]] == [reason]


def test_j8_an_undeclared_input_raises_before_any_model_call(accept):                      # criterion 17 (job), NODE-8a
    ran = accept.run("bad_input")
    record = ran.record
    assert ran.code == 1 and record["status"] == "failed", record
    assert "has no input `source`; its inputs are: sources" in record["summary"], record["summary"]
    assert record["model_calls"] == 0 and not ran.trace


def test_j9_a_precondition_written_in_the_procedure_that_is_unmet(accept):                 # criterion 3 (g), NODE-10
    ran = accept.run("guarded")
    r = ran.first
    reason = r["outputs"].get("reason")
    # The node's own reason, among its outputs and not beside them.
    assert r["outcome"] == "failed" and isinstance(reason, str) and reason and "reason" not in r, r
    assert ran.shell_commands() == [CHECK]    # the precondition was checked and no later step ran


def test_j10_a_declared_precondition_that_is_unmet_makes_no_model_call(accept):            # criterion 3 (f), NODE-13
    ran = accept.run("gated")
    r = ran.first
    assert r["outcome"] == "failed" and r["reason"] == "precondition_unmet" and r["message"] == NOT_READY, r
    assert ran.shell_commands() == [READY_CHECK] and ran.record["model_calls"] == 0    # the harness ran the check
    ready = accept.run("gated", sub="ready", ready=True)
    r = ready.first
    assert r["outcome"] == "done" and ready.shell_commands() == [READY_CHECK, "echo gated-work"], r


def test_j12_a_precondition_checked_by_a_function_that_returns_false(accept):              # criterion 3 (f), NODE-13
    ran = accept.run("gated_fn")
    r = ran.first
    assert r["reason"] == "precondition_unmet" and r["message"] == "The corpus alpha is never ready for this.", r
    assert ran.record["model_calls"] == 0 and ran.shell_commands() == []


@pytest.mark.parametrize("node,why", [
    ("gated_missing", "no tool `nosuchtool`"),
    ("gated_broken", "broken_check raised RuntimeError: the readiness file is unreadable"),
], ids=["missing_tool", "raising_function"])
def test_j13_a_check_that_cannot_be_run_is_an_error_not_an_unmet_check(accept, node, why):   # criterion 3 (f), NODE-13
    ran = accept.run(node)
    record = ran.record
    assert ran.code == 1 and record["status"] == "failed"
    assert record["summary"] == f"CheckError: the precondition check for `{node}` could not be run: {why}", record["summary"]
    assert record["model_calls"] == 0
    assert "must never be shown" not in str(record)    # the declared message is not shown


def test_j17_a_precondition_checked_by_a_servers_tool_that_returns_false(accept):          # criterion 3 (f), NODE-13
    ran = accept.run("gated_srv")
    r, saw = ran.first, ran.server_calls("ready")
    assert r["reason"] == "precondition_unmet" and r["message"] == "The corpus alpha is not marked ready.", r
    assert ran.record["model_calls"] == 0 and [x["args"] for x in saw] == [{"name": "alpha"}]
    ready = accept.run("gated_srv", sub="ready", ready=True)
    assert ready.first["outcome"] == "done" and ready.first["outputs"] == {"done_work": "gated-srv-work"}, ready.first


# --- criterion 20: a question in a job ----------------------------------------------------------------------------------


def test_j11_a_question_at_a_terminal_is_put_to_the_person_and_answered(accept):             # criterion 20, JOB-6
    ran = accept.run("refresh_missing", typed="polars")
    r, record = ran.first, ran.record
    asked = [c.result for c in ran.calls_of("refresh") if c.name == "ask"]
    assert record["attended"] is True and r["outcome"] == "done" and asked == ["polars"], (r, asked)
    assert f"[refresh#1] {QUESTION}" in ran.out    # put to the terminal, with the run's label in front
    assert "polars" in str(r["outputs"]["sources_updated"]) and record["failures"] == []
    declined = accept.run("refresh_missing", sub="no_ask", flags=("--no-ask",), typed="polars")
    r = declined.first
    assert declined.record["attended"] is False and r["reason"] == "needs_input" and r["question"] == QUESTION, r


def test_j19_two_nodes_that_ask_together_are_put_one_question_at_a_time(accept):           # criterion 20, JOB-6
    child, master, run_dir = accept.start_at_a_terminal("two_ask")
    os.set_blocking(child.stdout.fileno(), False)
    out, typed, shown_at, answered_at, during_hold = "", ["red", "blue"], [], [], []
    question = re.compile(r"\[asker#\d \w+\] Which colour for (\w+)\?")

    def read(seconds: float) -> list:
        nonlocal out
        if select.select([child.stdout], [], [], seconds)[0]:
            out += (child.stdout.read() or b"").decode()
        return question.findall(out)

    deadline = time.time() + 600
    while child.poll() is None and time.time() < deadline:
        asked = read(0.5)
        if len(asked) > len(answered_at):    # a question that has not been answered is on the terminal
            shown_at.append(time.time())
            if not answered_at:    # leave the first unanswered long enough for the other node to reach its own question
                hold = time.time() + 25
                while time.time() < hold:
                    asked = read(0.5)
                during_hold = list(asked)
            os.write(master, (typed[len(answered_at)] + "\n").encode())
            answered_at.append(time.time())
    child.wait(timeout=30)
    os.set_blocking(child.stdout.fileno(), True)
    out += child.stdout.read().decode()
    os.close(master)
    asked = question.findall(out)
    ran = accept.finished(child.returncode, out, run_dir)
    assert len(during_hold) == 1 and len(asked) == 2, (during_hold, asked)    # the second was not put during the wait
    assert len(shown_at) == 2
    gap = shown_at[1] - answered_at[0]    # the second node had asked meanwhile: no model call stood between
    assert gap < 2, gap
    want = {who: {"colour": colour} for who, colour in zip(asked, typed)}
    polars, ibis = ran.returned
    assert len(asked) == 2 and {"polars": polars["outputs"], "ibis": ibis["outputs"]} == want, (asked, ran.returned)


# --- criterion 21: function tools and tool failures --------------------------------------------------------------------


def test_j14_a_function_tool_is_called_by_a_script_and_by_the_model(accept):               # criterion 21 (job), TOOL-6
    ran = accept.run("tally")
    tally, ledger = (ran.returned + [{}, {}])[:2]
    counted = ran.function_calls("count_words")
    agent_pids = {q["pid"] for q in ran.trace}
    # `call` reaches a function tool and gets the function's own return value.
    assert ran.summary["direct"] == {"words": 3}
    assert tally["outcome"] == "done" and tally["outputs"] == {"words": 5}, tally
    assert [x["args"]["text"] for x in counted] == ["alpha beta gamma", "one two three four five"]
    # The function ran inside the harness process, and the tool server saw nothing.
    assert counted and {x["pid"] for x in counted} == agent_pids
    assert not (ran.dir / "tool_calls.jsonl").exists()
    offered = [sorted(q["tools"]) for q in ran.requests_of("tally")]
    assert offered and all(set(t) == JOB_VERBS | {"count_words"} for t in offered), offered[:1]
    # A function that raises gives the script the exception itself; the model goes on and the node exits `failed`.
    assert ran.summary["raised"] == "FileNotFoundError: no ledger named main", ran.summary["raised"]
    assert ledger["outcome"] == "failed" and "reason" not in ledger and len(ran.function_calls("read_ledger")) == 2, ledger


def test_j14_a_declared_function_that_cannot_be_imported_stops_the_run(accept):            # criterion 21, TOOL-16
    yaml = accept.edited("import", tool="missing: functions:no_such_function")
    ran = accept.run("nothing", sub="import", instance=yaml)
    want = 'error: instance.yaml: tool "missing": cannot import functions:no_such_function'
    assert ran.code == 2 and ran.out.strip() == want and not (ran.dir / "trace.jsonl").exists(), ran.out


def test_j15_the_harness_fills_a_functions_parameters_and_a_servers_error_is_an_exception(accept):   # criterion 21 (job)
    ran = accept.run("consult")
    consult, locate = (ran.returned + [{}, {}])[:2]
    summary = ran.summary
    by_source = {x["args"]["source"]: x["args"] for x in ran.function_calls("locate")}
    # Outside a node `state` is empty, and what one call wrote is not there for the next.
    assert summary["where"] == {"path": "/tmp/spike-corpus-alpha/ibis"}
    assert by_source["ibis"]["state"] == {} and by_source["narwhals"]["state"] == {}
    # Inside a node the harness filled `settings` and `state`, and `state` held the node's input.
    seen = by_source["polars"]
    assert locate["outcome"] == "done" and locate["outputs"] == {"path": WHERE}, locate
    assert seen["corpus_path"] == "/tmp/spike-corpus-alpha" and seen["state"]["source"] == "polars", seen
    # Calls in one response see the state as it was before that response: the node sets `phase` and then calls the tool.
    first = ran.requests_of("locate")[0]["response"]
    assert first is not None
    together = len(first["calls"]) > 1
    assert (seen["state"].get("phase") == "looking") == (not together), (together, seen["state"])
    shown = [q["params"].get("locate") for q in ran.requests_of("locate")]    # the filled parameters are not in the schema
    assert shown and all(p == ["source"] for p in shown), shown[:1]
    # A tool server's error is raised to the script, and the model goes on and exits `failed` by itself.
    assert summary["raised"].startswith("ToolError: ") and "no such key: missing" in summary["raised"], summary["raised"]
    assert consult["outcome"] == "failed" and "reason" not in consult and len(ran.server_calls("lookup")) == 2, consult


def test_j16_an_output_recorded_while_the_node_ran_counts_on_exit(accept):                 # criterion 21 (job), JOB-7a
    ran = accept.run("quiet")
    r, calls = ran.first, ran.calls_of("locate_quiet")
    if any(c.input.get("outputs") for c in calls if c.name == "exit"):
        pytest.skip("not exercised: the model gave `path` on EXIT")
    assert r["outcome"] == "done" and r["outputs"] == {"path": WHERE} and not rejected(calls), r


def test_j20_what_a_met_check_wrote_is_recorded_when_the_node_starts(accept):              # criterion 21 (job), NODE-11
    ran = accept.run("gated_rec")
    first, second = (ran.returned + [{}, {}])[:2]
    # A check that is not met records nothing, and the node does not start.
    assert second["reason"] == "precondition_unmet" and second["message"] == "The corpus alpha is not stamped.", second
    assert not ran.requests_of("gated_norec")
    # A function called after the node was run gets an empty `state`, not the state the check was given.
    after = [x["args"] for x in ran.function_calls("locate")]
    assert len(after) == 1 and after[0]["state"] == {}, after
    # What a met check wrote was recorded when the node started: the working value showed in the procedure from the
    # first model call, and the declared output counted on an EXIT that carried nothing.
    assert "Checked by: {{node.checked_by}}." in accept.node_file("gated_rec")    # the line is a placeholder in the node file, not fixed text
    seen = [q["system"] for q in ran.requests_of("gated_rec")]
    assert seen and "Checked by: the harness." in seen[0], seen[:1]
    if any(c.input.get("outputs") for c in ran.calls_of("gated_rec") if c.name == "exit"):
        pytest.skip("not exercised: the model gave `stamp` on EXIT")
    assert first["outcome"] == "done" and first["outputs"] == {"stamp": "ready-alpha"}, first


# --- criterion 22: tool servers ----------------------------------------------------------------------------------------


def test_j18_a_server_that_dies_is_reached_again_and_servers_keep_their_own_names(accept):   # criterion 22 (job)
    ran = accept.run("fetch_retry")
    s = ran.summary
    fetches, shells = ran.server_calls("fetch", "web"), ran.server_calls("shell")
    pids = {"fetch": [x["server_pid"] for x in fetches], "shell": [x["server_pid"] for x in shells]}
    # A call whose server dies gives the script ToolServerError, naming the server and the tool.
    assert s["first"] == f"ToolServerError: {FAULT}", s["first"]
    # The next call to that server connected again and worked.
    assert s["second"] == "fetched https://example.org/a" and len(fetches) == 3, s
    assert fetches[0]["server_pid"] != fetches[1]["server_pid"], pids
    # One connection to each server is held: later calls reached one process.
    assert fetches[1]["server_pid"] == fetches[2]["server_pid"] and len(shells) == 2, pids
    assert shells[0]["server_pid"] == shells[1]["server_pid"], pids
    # Two servers each have a tool named `note`: `web__note` and `tools__note` reach their own server.
    assert s["notes"] == ["noted on web", "noted"] and len(ran.server_calls("note", "web")) == 1, s["notes"]
    assert len(ran.server_calls("note")) == 1


def test_j18_an_uncaught_server_error_in_a_node_fails_the_job_and_names_node_and_server(accept):   # criterion 22 (job)
    ran = accept.run("fetch_down")
    record, fetches = ran.record, ran.server_calls("fetch", "web")
    assert ran.code == 1 and record["status"] == "failed", record
    assert record["summary"] == f"ToolServerError: {FAULT}", record["summary"]
    assert record["failures"] == [{"node": "fetcher", "error": f"ToolServerError: {FAULT}"}], record["failures"]
    # The model was not shown the fault: no model call followed the call that could not be made.
    reqs = ran.trace
    assert len(fetches) == 1 and reqs and all(q["ts"] < fetches[0]["ts"] for q in reqs), (len(reqs), len(fetches))


@pytest.mark.parametrize("sub,spec,want", [
    ("command", "{command: corpus-web}", 'error: tool server "web" could not be started: no such command "corpus-web"'),
    ("address", "{url: 'http://127.0.0.1:9/mcp'}", 'error: tool server "web" could not be reached at http://127.0.0.1:9/mcp'),
    ("exits", "{command: 'false'}", 'error: tool server "web" could not be started: it closed the connection before answering'),
], ids=["no_command", "no_address", "exits_at_once"])
def test_j18_a_server_that_cannot_be_started_stops_the_job_naming_it(accept, sub, spec, want):   # criterion 22 (job)
    yaml = accept.edited(sub, replace=("web: {command: python, args: [../servers/flaky_server.py]}", f"web: {spec}"))
    ran = accept.run("nothing", sub=sub, instance=yaml)
    assert (ran.code, ran.out.strip()) == (2, want)
    assert not (ran.dir / "trace.jsonl").exists()


def test_j18_a_function_named_like_a_servers_tool_stops_the_job_naming_both(accept):       # criterion 22 (job)
    yaml = accept.edited("same_name", tool="tools__shell: functions:count_words")
    ran = accept.run("nothing", sub="same_name", instance=yaml)
    want = 'error: instance.yaml: two tools are named "tools__shell": function functions:count_words and server "tools"'
    assert (ran.code, ran.out.strip()) == (2, want)
