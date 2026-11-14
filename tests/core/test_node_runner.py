import asyncio
from pathlib import Path

import pytest

from agent_core.contracts import HandoverRequest, Message, ModelResponse, RunEnd, ToolServerError, ToolSpec
from agent_core.core.checks import CheckError
from agent_core.core.node_runner import NodeRunError, make_brief
from agent_core.core.record import NodeRunNote
from agent_core.core.registry import provider
from agent_core.core.settings import load_settings
from agent_core.core.state import HarnessState, Slot
from agent_core.resources.folder import FolderResources

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "instance"
FAILED_EXIT = [[["exit", {"outcome": "failed", "outputs": {"reason": "x"}}]]]
DONE_WITH_BRANCH = [
    [["tools__shell", {"command": "echo checked alpha"}]],
    [["state_set", {"key": "branch", "value": "refresh/alpha"}]],
    [["tools__shell", {"command": "echo updating polars"}]],
    [["exit", {"outcome": "done", "outputs": {"sources_updated": "polars"}}]],
]
PROCEDURE_LINE = "# Procedure of the node that is running: `refresh`"


class Raising:
    """A driver whose provider fails."""

    def __init__(self, error):
        self.error = error

    async def drive(self, brief, controller):
        raise self.error


class Reporting:
    """A driver that makes responses reporting the given token counts `(sent, cache_read, cache_written)`, then stops."""

    def __init__(self, *counts):
        self.counts = counts

    async def drive(self, brief, controller):
        for sent, read, written in self.counts:
            await controller.responded(ModelResponse("", (), sent, read, written))
        return RunEnd(by_controller=False, said="done talking")


# --- the brief ---------------------------------------------------------------------------------------------------


async def test_the_brief_of_a_job_has_its_five_parts_and_its_tools(run_node):
    r = await run_node("refresh", {"sources": "polars"}, script=FAILED_EXIT)
    assert [source for source, _ in r.note.parts] == ["engine: rules", "engine: inside a node", "procedure conventions", "policy", "node file: skills/refresh/SKILL.md"]
    assert r.note.tools == ["exit", "ask", "state_set", "state_get", "load", "tools__shell"]
    assert "## Routing" not in r.brief.instructions and "Sources to update: polars." in r.brief.instructions and r.brief.handover == ()


async def test_the_parts_are_in_the_instructions_in_order_and_the_note_counts_their_size(run_node, instance):
    r = await run_node("refresh", {"sources": "polars"}, script=FAILED_EXIT)
    text = r.brief.instructions
    marks = [text.index("# Engine rules"), text.index("## Inside a node"), text.index("## Steps of a procedure"),
             text.index(instance.policy.strip()), text.index(PROCEDURE_LINE)]
    assert marks == sorted(marks) and len(set(marks)) == 5
    assert all(size > 0 for _, size in r.note.parts)
    assert sum(size for _, size in r.note.parts) <= len(text)


async def test_the_procedure_line_is_written_once_and_the_outcomes_follow_it(run_node):
    r = await run_node("refresh", {"sources": "polars"}, script=FAILED_EXIT)
    lines = r.brief.instructions.splitlines()
    assert lines.count(PROCEDURE_LINE) == 1 and sum("Procedure of the node that is running" in line for line in lines) == 1
    assert lines[lines.index(PROCEDURE_LINE) + 1] == "The outcomes of this node are: done, declined, failed."
    assert r.brief.instructions.index("# Refresh") > r.brief.instructions.index(PROCEDURE_LINE)
    assert r.brief.opening == "Run the node." and r.brief.tools[0].name == "exit"


async def test_a_nodes_own_failed_exit_carries_its_reason_among_the_outputs(run_node):     # criterion 3 (e)
    r = await run_node("refresh", {"sources": "polars"}, script=FAILED_EXIT)
    assert r.result == {"outcome": "failed", "outputs": {"reason": "x"}}


async def test_a_node_that_runs_to_done_returns_its_outputs(run_node):
    r = await run_node("refresh", {"sources": "polars"}, script=DONE_WITH_BRANCH)
    assert r.result == {"outcome": "done", "outputs": {"sources_updated": "polars", "branch": "refresh/alpha"}}
    assert r.note.model_calls == 4 and r.note.label == "refresh#1" and r.note.node == "refresh" and r.note.handover == []


def test_make_brief_passes_the_handover_and_the_opening_on(instance):
    handover = (Message("user", "Update polars."), Message("agent", "Which sources?"))
    slot = Slot("refresh", {"sources": "polars"}, {}, {})
    state = HarnessState(session={}, node=slot)
    tools = {"tools__shell": (None, ToolSpec("tools__shell", "Run a command.", {"type": "object"}))}
    brief, parts = make_brief(
        instance, instance.nodes["refresh"], slot, state, settings=load_settings(instance, [FIXTURE / "config" / "alpha.yaml"]),
        resources=FolderResources(instance.root), tools=tools, job=True, handover=handover, opening="Carry on.",
    )
    assert brief.handover == handover and brief.opening == "Carry on." and [t.name for t in brief.tools][-1] == "tools__shell"
    assert [source for source, _ in parts][-1] == "node file: skills/refresh/SKILL.md"
    assert "\n\n".join(text for _, text in parts) == brief.instructions


# --- before the node starts ------------------------------------------------------------------------------------


async def test_unmet_precondition_makes_no_driver_call(run_node):                           # criterion 3 (f)
    r = await run_node("gated", {}, script=[[["never", {}]]])
    assert r.result == {"outcome": "failed", "reason": "precondition_unmet", "message": "The corpus alpha is not ready: there is no alpha.ready file.", "outputs": {}}
    assert r.note is None and r.brief is None


async def test_a_check_written_in_python_that_is_not_met_fails_the_same_way(run_node):
    r = await run_node("gated_fn", {}, script=[[["never", {}]]])
    assert r.result == {"outcome": "failed", "reason": "precondition_unmet", "message": "The corpus alpha is never ready for this.", "outputs": {}}
    assert r.note is None


async def test_what_a_met_check_wrote_shows_in_the_procedure_and_counts_on_exit(run_node):  # NODE-11
    r = await run_node("gated_rec", {}, script=[[["exit", {"outcome": "done", "outputs": {}}]]])
    assert "Checked by: the harness." in r.brief.instructions and r.result == {"outcome": "done", "outputs": {"stamp": "ready-alpha"}}


@pytest.mark.parametrize("node", ["gated_broken", "gated_missing"])
async def test_a_check_that_cannot_be_run_raises_check_error_and_makes_no_driver_call(run_node, node):
    with pytest.raises(CheckError, match=f"the precondition check for `{node}` could not be run"):
        await run_node(node, {}, script=[[["never", {}]]])


async def test_unknown_input_raises_before_anything(run_node):                             # criterion 17
    with pytest.raises(ValueError, match="has no input `source`; its inputs are: sources"):
        await run_node("refresh", {"source": "polars"}, script=[])


async def test_an_unknown_input_is_refused_before_a_check_is_run(run_node, run_dir):
    with pytest.raises(ValueError, match="`gated` has no input `x`; it takes no inputs"):
        await run_node("gated", {"x": 1}, script=[])


async def test_a_placeholder_the_settings_lack_fails_the_run_without_a_driver_call(run_node, broken, load):   # TPL-6b
    broken.append("skills/refresh/SKILL.md", "\nSecret: {{settings.NO_SUCH_SETTING}}.\n")
    r = await run_node("refresh", {"sources": "polars"}, script=[[["never", {}]]], target=load())
    assert r.result == {
        "outcome": "failed", "reason": "unknown_placeholder", "outputs": {},
        "detail": "unknown placeholder {{settings.NO_SUCH_SETTING}} in skills/refresh/SKILL.md",
    }
    assert r.note is None


async def test_a_fragment_loop_fails_the_run_the_same_way(run_node, broken, load):          # TPL-2b
    broken.append("skills/refresh/SKILL.md", "\n{{include fragments/loop_a.md}}\n")
    r = await run_node("refresh", {"sources": "polars"}, script=[[["never", {}]]], target=load())
    assert r.result["outcome"] == "failed" and r.result["reason"] == "unknown_placeholder" and r.result["outputs"] == {}
    assert "includes itself" in r.result["detail"] and r.note is None


async def test_a_placeholder_the_settings_lack_in_a_check_message_fails_the_same_way(run_node, broken, load):
    file = broken.root / "skills" / "gated_fn" / "SKILL.md"
    file.write_text(file.read_text().replace("{{settings.CORPUS_NAME}} is never", "{{settings.NO_SUCH_SETTING}} is never"))
    r = await run_node("gated_fn", {}, script=[[["never", {}]]], target=load())
    assert r.result["reason"] == "unknown_placeholder" and "NO_SUCH_SETTING" in r.result["detail"] and r.note is None


async def test_a_tool_no_source_offers_is_named_in_an_error(run_node, broken, load):
    broken.frontmatter("refresh", **{"allowed-tools": "[tools__nope]"})
    with pytest.raises(ValueError, match="`refresh` declares the tool `tools__nope`, which no tool source offers"):
        await run_node("refresh", {"sources": "polars"}, script=[[["never", {}]]], target=load())


async def test_a_node_the_instance_does_not_have_is_named_in_an_error(run_node):
    with pytest.raises(ValueError, match="no node `nothing`; the nodes are: "):
        await run_node("nothing", {}, script=[])


# --- how the run ends --------------------------------------------------------------------------------------------


async def test_the_model_stopping_is_no_exit(run_node):                                     # criterion 3 (d)
    r = await run_node("silent", {}, script=["I will not exit."])
    assert r.result == {"outcome": "failed", "reason": "no_exit", "said": "I will not exit.", "outputs": {}}


async def test_a_script_that_runs_out_after_calls_is_no_exit_with_nothing_said(run_node):
    r = await run_node("refresh", {}, script=[[["state_set", {"key": "scratch", "value": 1}]]])
    assert r.result == {"outcome": "failed", "reason": "no_exit", "said": "", "outputs": {}}


async def test_a_dead_tool_server_is_raised_to_the_caller(run_node):                        # TOOL-11e
    r = await run_node("fetcher", {}, script=[[["web__fetch", {"url": "https://example.org/a"}]]])
    assert isinstance(r.fault, ToolServerError) and r.result is None and "web" in str(r.fault)


async def test_a_provider_failure_names_the_run(run_node):                                  # Review Focus 1
    error = RuntimeError("rate limit")
    with pytest.raises(NodeRunError, match=r"^refresh#1: RuntimeError: rate limit$") as caught:
        await run_node("refresh", {"sources": "polars"}, driver=Raising(error), label="refresh#1")
    assert caught.value.__cause__ is error


async def test_a_provider_failure_still_leaves_a_note_of_the_run(open_runner):
    notes = []
    async with open_runner(notes=notes) as runner:
        with pytest.raises(NodeRunError):
            await runner.run("refresh", {"sources": "polars"}, driver=Raising(RuntimeError("down")), label="refresh#4")
    assert [(n.label, n.node, n.model_calls) for n in notes] == [("refresh#4", "refresh", 0)]


async def test_the_person_is_asked_with_the_label_of_the_run(run_node):                    # JOB-6
    class Answering:
        asked = []

        async def tell(self, text): ...

        async def ask(self, question, label=""):
            self.asked.append((question, label))
            return "polars"

    person = Answering()
    r = await run_node("refresh", {}, person=person, label="refresh#7", script=[[["ask", {"question": "Which sources?"}]], FAILED_EXIT[0]])
    assert person.asked == [("Which sources?", "refresh#7")] and r.result == {"outcome": "failed", "outputs": {"reason": "x"}}


# --- fresh facts -------------------------------------------------------------------------------------------------


async def test_each_run_starts_from_fresh_facts(run_node):                                  # JOB-4
    await run_node("refresh", {"sources": "polars"}, script=DONE_WITH_BRANCH)
    r = await run_node("refresh", {"sources": "ibis"}, script=DONE_WITH_BRANCH)
    assert "Branch: not set." in r.brief.instructions


async def test_one_runner_gives_each_run_fresh_facts_in_turn_and_at_once(open_runner):      # JOB-4, JOB-8
    from agent_core.backends.scripted import ScriptedBackend

    async with open_runner() as runner:
        first = await runner.run("refresh", {"sources": "polars"}, driver=ScriptedBackend(script=DONE_WITH_BRANCH), label="refresh#1")
        briefs = []

        class Seeing(ScriptedBackend):
            async def drive(self, brief, controller):
                briefs.append(brief.instructions)
                return await super().drive(brief, controller)

        both = await asyncio.gather(
            runner.run("refresh", {"sources": "ibis"}, driver=Seeing(script=DONE_WITH_BRANCH), label="refresh#2"),
            runner.run("refresh", {"sources": "narwhals"}, driver=Seeing(script=DONE_WITH_BRANCH), label="refresh#3"),
        )
    assert first["outputs"]["branch"] == "refresh/alpha" and [r["outcome"] for r in both] == ["done", "done"]
    assert len(briefs) == 2 and all("Branch: not set." in text for text in briefs)
    assert "Sources to update: ibis." in briefs[0] and "Sources to update: narwhals." in briefs[1]


# --- the note of a run -------------------------------------------------------------------------------------------


async def test_token_counts_are_not_known_on_the_scripted_backend(run_node):               # SCOPE-7
    r = await run_node("refresh", {"sources": "polars"}, script=FAILED_EXIT)
    assert r.note.model_calls == 1 and r.note.tokens_sent is None and r.note.cache_read is None and r.note.cache_written is None


async def test_token_counts_are_added_up_over_the_responses_of_a_run(run_node):
    r = await run_node("silent", {}, driver=Reporting((100, 0, 40), (30, 40, 0)))
    assert (r.note.model_calls, r.note.tokens_sent, r.note.cache_read, r.note.cache_written) == (2, 130, 40, 40)


async def test_one_response_that_does_not_report_a_count_makes_it_unknown_for_the_whole_run(run_node):
    r = await run_node("silent", {}, driver=Reporting((100, None, 40), (30, 40, None)))
    assert (r.note.model_calls, r.note.tokens_sent, r.note.cache_read, r.note.cache_written) == (2, 130, None, None)
    r = await run_node("silent", {}, driver=Reporting((None, 1, 1), (30, 1, 1)))
    assert (r.note.tokens_sent, r.note.cache_read, r.note.cache_written) == (None, 2, 2)


async def test_a_run_with_no_response_has_counts_of_zero(run_node):
    r = await run_node("silent", {}, driver=Reporting())
    assert r.note == NodeRunNote(
        label="silent#1", node="silent", parts=r.note.parts, tools=["exit", "ask", "state_set", "state_get", "load"], handover=[],
    )
    assert (r.note.model_calls, r.note.tokens_sent, r.note.cache_read, r.note.cache_written) == (0, 0, 0, 0)


# --- the none strategy -------------------------------------------------------------------------------------------


async def test_the_none_strategy_hands_over_nothing():                                      # CTX
    strategy = provider("context", "none")()

    async def summarise(system, text):
        raise AssertionError("the none strategy does not summarise")

    request = HandoverRequest(
        transcript=(Message("user", "hello"),), facts={"a": 1}, node="refresh", inputs={}, summarise=summarise,
    )
    assert await strategy.build(request) == ()
