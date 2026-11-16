import pytest

from agent_core.contracts import EndRun, ToolServerError
from agent_core.core.controller import ALONE, VERB_SPECS, VERBS
from records import function_calls, shell_commands, tool_calls

DONE = [["exit", {"outcome": "done", "outputs": {}}]]
TOGETHER = (
    "refused: `ask`, `enter` and `exit` must be the only call in a response. "
    "None of the calls in this response ran. Send them again, separately."
)


class KeepsGoing:
    """A driver that does not honour `EndRun`: it makes every call of its script, as a careless provider might."""

    def __init__(self, calls):
        self.calls = calls
        self.answers = []

    async def drive(self, brief, controller):
        from agent_core.contracts import ModelResponse, RunEnd, ToolCall

        for n, (name, args) in enumerate(self.calls):
            call = ToolCall(f"keep_{n}", name, args)
            await controller.responded(ModelResponse("", (call,), None, None, None))
            self.answers.append(await controller.handle(call))
        return RunEnd(by_controller=False, said="")


class Answering:
    """A person who answers each question with `answer` and remembers what was asked."""

    def __init__(self, answer):
        self.answer, self.asked, self.told = answer, [], []

    async def tell(self, text):
        self.told.append(text)

    async def ask(self, question, label=""):
        self.asked.append((question, label))
        return self.answer


def test_the_six_verbs_each_have_a_spec():
    assert VERBS == {"enter", "exit", "ask", "state_set", "state_get", "load"} == set(VERB_SPECS)
    assert all(spec.name == name and spec.description and spec.schema["type"] == "object" for name, spec in VERB_SPECS.items())
    assert ALONE == {"ask", "enter", "exit"}


# --- EXIT -------------------------------------------------------------------------------------------------------


async def test_exit_with_a_wrong_output_is_returned_once_then_accepted(run_node):          # criterion 3 (b)
    r = await run_node("shape", {}, script=[[["exit", {"outcome": "done", "outputs": {"count": "three"}}]],
                                            [["exit", {"outcome": "done", "outputs": {"count": 3}}]]])
    assert r.result == {"outcome": "done", "outputs": {"count": 3}} and r.slot_rejections == 1
    assert r.record[0].result.startswith("the outputs do not match the node's output schema: [")
    assert r.record[0].result.endswith("]. Correct them and EXIT again.")


async def test_two_wrong_outputs_end_as_invalid_output(run_node):                          # criterion 3 (c)
    r = await run_node("shape", {}, script=[[["exit", {"outcome": "done", "outputs": {"count": "three"}}]]] * 2)
    assert r.result["reason"] == "invalid_output" and r.result["outputs"] == {} and r.result["errors"]
    assert r.result["outcome"] == "failed" and r.controller.ended


async def test_done_without_a_required_output_is_sent_back(run_node):                      # JOB-7a
    r = await run_node("shape", {}, script=[[["exit", {"outcome": "done", "outputs": {}}]], [["exit", {"outcome": "done", "outputs": {"count": 3}}]]])
    assert r.result == {"outcome": "done", "outputs": {"count": 3}}
    assert "do not match the node's output schema" in r.record[0].result and "count" in r.record[0].result


async def test_an_output_recorded_by_a_function_need_not_be_given_on_exit(run_node):       # JOB-7a, criterion 21
    r = await run_node("locate_quiet", {"source": "polars"}, script=[[["locate", {"source": "polars"}]], [["exit", {"outcome": "done", "outputs": {}}]]])
    assert r.result == {"outcome": "done", "outputs": {"path": "/tmp/spike-corpus-alpha/polars"}}


async def test_the_value_on_exit_stands_over_one_that_was_recorded(run_node):              # JOB-7a
    r = await run_node("locate_quiet", {"source": "polars"}, script=[
        [["locate", {"source": "polars"}]], [["exit", {"outcome": "done", "outputs": {"path": "/elsewhere"}}]]])
    assert r.result == {"outcome": "done", "outputs": {"path": "/elsewhere"}}


async def test_an_outcome_the_node_does_not_declare_is_an_error_and_the_run_goes_on(run_node):   # JOB-7a
    r = await run_node("shape", {}, script=[[["exit", {"outcome": "declined", "outputs": {}}]], [["exit", {"outcome": "failed", "outputs": {}}]]])
    assert r.record[0].result == "`declined` is not an outcome of `shape`; its outcomes are: done, failed, skipped, stopped"
    assert r.slot_rejections == 0
    assert r.result == {"outcome": "failed", "outputs": {}}


async def test_exit_accepts_skipped_and_stopped_for_any_node(run_node):                     # SEQ-8
    for outcome in ("skipped", "stopped"):
        r = await run_node("shape", {}, script=[[["exit", {"outcome": outcome, "outputs": {}}]]])
        assert r.result == {"outcome": outcome, "outputs": {}}


async def test_another_outcome_may_carry_an_undeclared_reason_and_done_may_not(run_node):  # JOB-13
    r = await run_node("shape", {}, script=[[["exit", {"outcome": "failed", "outputs": {"reason": "no words"}}]]])
    assert r.result == {"outcome": "failed", "outputs": {"reason": "no words"}}
    r = await run_node("shape", {}, script=[[["exit", {"outcome": "done", "outputs": {"count": 3, "reason": "x"}}]]] * 2)
    assert r.result["reason"] == "invalid_output" and any("reason" in e for e in r.result["errors"])


async def test_an_exit_whose_outputs_are_not_an_object_is_sent_back(run_node):
    r = await run_node("shape", {}, script=[[["exit", {"outcome": "failed", "outputs": "x"}]], [["exit", {"outcome": "failed", "outputs": {}}]]])
    assert "do not match the node's output schema" in r.record[0].result and r.result == {"outcome": "failed", "outputs": {}}


# --- calls that must be alone ---------------------------------------------------------------------------------


async def test_a_call_beside_exit_refuses_both_and_runs_neither(run_node, run_dir):        # VERB-6
    r = await run_node("refresh", {"sources": "polars"}, script=[
        [["tools__shell", {"command": "echo both"}], ["exit", {"outcome": "done", "outputs": {}}]]])
    assert [m.result.startswith("refused") for m in r.record] == [True, True] and shell_commands(run_dir) == []
    assert [m.result for m in r.record] == [TOGETHER, TOGETHER] and r.run.result is None


@pytest.mark.parametrize("alone", [["ask", {"question": "Which?"}], ["enter", {"node": "status"}]])
async def test_a_call_beside_ask_or_enter_is_refused_with_it(run_node, run_dir, alone):   # VERB-6a, VERB-6b
    r = await run_node("refresh", {}, script=[[alone, ["tools__shell", {"command": "echo both"}]]])
    assert [m.result for m in r.record] == [TOGETHER, TOGETHER] and shell_commands(run_dir) == []


async def test_a_response_of_calls_that_may_share_one_runs_them_all(run_node, run_dir):    # VERB-6
    r = await run_node("refresh", {"sources": "polars"}, script=[
        [["tools__shell", {"command": "echo one"}], ["tools__shell", {"command": "echo two"}]]])
    assert shell_commands(run_dir) == ["echo one", "echo two"] and all(not m.result.startswith("refused") for m in r.record)


# --- what a node declares ------------------------------------------------------------------------------------


async def test_an_undeclared_tool_is_refused_and_not_called(run_node, run_dir):            # criterion 14
    r = await run_node("plain", {}, script=[[["tools__shell", {"command": "echo plain-work"}]]])
    assert r.record[0].result == "refused: `tools__shell` is not declared by the node that is running" and shell_commands(run_dir) == []


async def test_another_tool_of_a_server_is_refused_too(run_node, run_dir):                 # NODE-6b
    r = await run_node("refresh", {"sources": "polars"}, script=[[["tools__note", {"text": "x"}]]])
    assert r.record[0].result == "refused: `tools__note` is not declared by the node that is running"
    assert tool_calls(run_dir, "note") == []


# --- state_set, state_get, load ---------------------------------------------------------------------------


async def test_state_set_is_recorded_and_says_so(run_node):                                # SCOPE-4
    r = await run_node("refresh", {}, script=[[["state_set", {"key": "sources", "value": "polars"}]]])
    assert r.record[0].result == 'recorded sources = "polars"' and r.slot.inputs == {"sources": "polars"}


async def test_state_set_goes_where_the_name_belongs(run_node):                            # ST-4
    r = await run_node("refresh", {"sources": "polars"}, script=[
        [["state_set", {"key": "branch", "value": "refresh/alpha"}]], [["state_set", {"key": "scratch", "value": [1, 2]}]]])
    assert r.state.session == {"branch": "refresh/alpha"} and r.slot.outputs == {"branch": "refresh/alpha"}
    assert r.slot.values == {"scratch": [1, 2]} and r.record[1].result == "recorded scratch = [1, 2]"


async def test_state_get_reads_inputs_values_and_facts_and_says_when_not_set(run_node):
    r = await run_node("refresh", {"sources": "polars"}, session={"tag": "t"}, script=[
        [["state_set", {"key": "scratch", "value": {"a": 1}}]],
        [["state_get", {"key": "sources"}]], [["state_get", {"key": "scratch"}]], [["state_get", {"key": "tag"}]],
        [["state_get", {"key": "nothing"}]]])
    assert [m.result for m in r.record[1:]] == ['"polars"', '{"a": 1}', '"t"', "not set"]


async def test_load_reads_a_file_of_the_instance_and_says_when_it_cannot(run_node):
    r = await run_node("refresh", {}, script=[[["load", {"path": "fragments/safety.md"}]], [["load", {"path": "nothing.md"}]],
                                              [["load", {"path": "../outside.md"}]]])
    assert r.record[0].result == (r.resources.read("fragments/safety.md"))
    assert r.record[1].result.startswith("error: no file `nothing.md`") and r.record[2].result.startswith("error: ")


# --- tools -------------------------------------------------------------------------------------------------------


async def test_a_function_is_given_the_state_and_what_it_wrote_is_recorded_and_listed(run_node, run_dir):   # TOOL-12
    r = await run_node("locate", {"source": "polars"}, script=[[["locate", {"source": "polars"}]]])
    path = "/tmp/spike-corpus-alpha/polars"
    assert r.record[0].result == (
        f'{{"path": "{path}"}}\n\n(recorded by this call: path = "{path}", last_located = "polars")'
    )
    assert r.state.session == {"path": path} and r.slot.outputs == {"path": path} and r.slot.values == {"last_located": "polars"}
    assert function_calls(run_dir, "locate")[0]["args"]["state"] == {"source": "polars"}


async def test_a_function_that_raises_records_nothing_and_the_model_is_told(run_node):     # TOOL-12, TOOL-11a
    r = await run_node("ledger", {}, script=[[["read_ledger", {"name": "main"}]]])
    assert r.record[0].result == "error: read_ledger raised FileNotFoundError: no ledger named main"
    assert r.slot.values == {} and r.state.session == {} and r.fault is None


async def test_a_function_that_writes_nothing_has_nothing_listed(run_node):
    r = await run_node("tally", {}, script=[[["count_words", {"text": "one two three"}]]])
    assert r.record[0].result == '{"words": 3}'


async def test_a_servers_own_error_goes_to_the_model_as_its_message(run_node):             # TOOL-11a
    r = await run_node("consult", {}, script=[[["tools__lookup", {"key": "motto"}]]])
    assert r.record[0].result.startswith("error: ") and "no such key: motto" in r.record[0].result
    assert r.fault is None and not r.controller.ended


async def test_a_servers_text_is_the_result(run_node):
    r = await run_node("refresh", {"sources": "polars"}, script=[[["tools__shell", {"command": "echo hi"}]]])
    assert '"stdout": "hi\\n"' in r.record[0].result and not r.record[0].result.startswith("error")


async def test_a_dead_server_ends_the_run_with_a_fault(run_node):                          # TOOL-11e
    r = await run_node("fetcher", {}, script=[[["web__fetch", {"url": "https://example.org/a"}]]])
    assert isinstance(r.fault, ToolServerError) and r.result is None and r.controller.ended
    assert "web" in str(r.fault)


async def test_a_dead_server_answers_end_run_and_is_not_recorded(run_node):
    keeps = KeepsGoing([["web__fetch", {"url": "https://example.org/a"}]])
    r = await run_node("fetcher", {}, driver=keeps)
    assert keeps.answers == [EndRun()] and r.record == []


# --- one response ---------------------------------------------------------------------------------------------


async def test_a_value_set_in_the_same_response_is_not_in_the_functions_state(run_node, run_dir):   # CTL-5
    await run_node("locate", {"source": "polars"}, script=[
        [["state_set", {"key": "phase", "value": "looking"}], ["locate", {"source": "polars"}]],
        [["exit", {"outcome": "done", "outputs": {}}]]])
    assert "phase" not in function_calls(run_dir, "locate")[0]["args"]["state"]


async def test_a_value_set_in_an_earlier_response_is_in_the_functions_state(run_node, run_dir):   # CTL-5
    await run_node("locate", {"source": "polars"}, script=[
        [["state_set", {"key": "phase", "value": "looking"}]], [["locate", {"source": "polars"}]]])
    assert function_calls(run_dir, "locate")[0]["args"]["state"]["phase"] == "looking"


async def test_what_the_calls_of_a_response_wrote_is_applied_in_its_order(run_node):       # CTL-5, VERB-6c
    r = await run_node("locate", {"source": "polars"}, script=[
        [["state_set", {"key": "phase", "value": "first"}], ["state_get", {"key": "phase"}],
         ["state_set", {"key": "phase", "value": "second"}], ["state_get", {"key": "phase"}]]])
    assert [m.result for m in r.record] == ['recorded phase = "first"', "not set", 'recorded phase = "second"', "not set"]
    assert r.slot.values == {"phase": "second"}


async def test_each_response_is_counted_in_the_usage(run_node):
    r = await run_node("refresh", {}, script=[[["state_set", {"key": "a", "value": 1}]], "that is all"])
    assert [tuple(c.name for c in u.calls) for u in r.usage] == [("state_set",), ()]


# --- ask --------------------------------------------------------------------------------------------------------


async def test_ask_with_nobody_there_ends_as_needs_input(run_node):                        # criterion 3 (a)
    r = await run_node("refresh", {}, script=[[["ask", {"question": "Which sources should I update?"}]], [["never", {}]]])
    assert r.result == {"outcome": "failed", "reason": "needs_input", "question": "Which sources should I update?", "outputs": {}}
    assert r.controller.ended and r.record == []


async def test_a_person_answers_with_the_run_label_given_and_the_answer_is_the_result(run_node):   # JOB-6
    person = Answering("polars")
    r = await run_node("refresh", {}, person=person, label="refresh#3", script=[
        [["ask", {"question": "Which sources should I update?"}]], [["state_set", {"key": "sources", "value": "polars"}]]])
    assert person.asked == [("Which sources should I update?", "refresh#3")]
    assert r.record[0].result == "polars" and r.run.result is None and not r.controller.ended


# --- the end of the run ---------------------------------------------------------------------------------------


async def test_after_the_run_has_ended_a_call_is_not_run(run_node, run_dir):                # CTL-7
    keeps = KeepsGoing([["exit", {"outcome": "failed", "outputs": {}}], ["tools__shell", {"command": "echo late"}],
                        ["state_set", {"key": "late", "value": 1}]])
    r = await run_node("refresh", {"sources": "polars"}, driver=keeps)
    assert keeps.answers[0] == EndRun()
    assert [a.text for a in keeps.answers[1:]] == ["not run: the node run has ended"] * 2
    assert shell_commands(run_dir) == [] and "late" not in r.slot.values and r.result == {"outcome": "failed", "outputs": {}}


async def test_the_model_stopping_ends_a_job_without_a_reply(run_node):                    # JOB-12
    r = await run_node("silent", {}, script=["I will not exit."])
    assert r.run.result is None and await r.controller.stopped("I will not exit.") is None
