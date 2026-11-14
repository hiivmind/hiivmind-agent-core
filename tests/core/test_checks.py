import dataclasses
from pathlib import Path

import pytest

from agent_core.contracts.errors import ToolError, ToolServerError
from agent_core.contracts.values import ToolSpec
from agent_core.core.checks import CheckError, unknown_inputs, unmet_precondition
from agent_core.core.instance import load_instance
from agent_core.core.settings import load_settings
from agent_core.core.templates import render
from agent_core.resources.folder import FolderResources
from agent_core.tools.function import FunctionSource
from agent_core.tools.mcp_server import McpServerSource

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "instance"


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    directory = tmp_path / "run"
    directory.mkdir()
    monkeypatch.setenv("AGENT_CORE_RUN_DIR", str(directory))
    return directory


@pytest.fixture
async def sources(instance, run_dir):
    """The fixture instance's function and server tools, as the tools mapping the checks use."""
    settings = load_settings(instance, [FIXTURE / "config" / "alpha.yaml"])
    env = {"AGENT_CORE_INSTANCE": str(FIXTURE), "AGENT_CORE_RUN_DIR": str(run_dir)}
    functions = FunctionSource(instance.functions, settings, FIXTURE)
    servers = McpServerSource(instance.servers, env, FIXTURE)
    tools = {}
    for source in (functions, servers):
        for spec in await source.tools():
            tools[spec.name] = (source, spec)
    yield tools, settings
    await servers.close()


@pytest.fixture
def checks(instance, sources):
    tools, settings = sources

    async def run(node_name, inputs=None, facts=None, node=None):
        node = node or instance.nodes[node_name]
        inputs, facts = inputs or {}, facts or {}

        def fill(text):
            return render(
                text, file=node.file, settings=settings, inputs=inputs, session=facts, values={},
                resources=FolderResources(FIXTURE),
            )

        return await unmet_precondition(
            node, inputs, facts, tools=tools, functions=set(instance.functions), fill=fill
        )

    return run


def test_unknown_input_names_the_declared_ones(instance):
    assert unknown_inputs(instance.nodes["refresh"], {"source": "x"}) == "`refresh` has no input `source`; its inputs are: sources"


def test_known_inputs_and_no_inputs_are_accepted(instance):
    assert unknown_inputs(instance.nodes["refresh"], {"sources": "x"}) is None
    assert unknown_inputs(instance.nodes["refresh"], {}) is None


def test_a_node_without_inputs_says_so(instance):
    assert unknown_inputs(instance.nodes["gated"], {"x": 1}) == "`gated` has no input `x`; it takes no inputs"


async def test_shell_check_is_met_on_exit_zero(checks, run_dir):
    assert (await checks("gated"))[0] == "The corpus alpha is not ready: there is no alpha.ready file."
    (run_dir / "alpha.ready").touch()
    assert (await checks("gated"))[0] is None


async def test_function_check_false_is_unmet_and_true_leaves_what_it_wrote(checks):
    assert (await checks("gated_fn"))[0] == "The corpus alpha is never ready for this."
    message, wrote = await checks("gated_rec")
    assert message is None and dict(wrote) == {"stamp": "ready-alpha", "checked_by": "the harness"}


async def test_an_unmet_check_records_nothing(checks):
    message, wrote = await checks("gated_norec")
    assert message == "The corpus alpha is not stamped." and wrote == []


async def test_another_servers_tool_is_unmet_only_on_false(checks, run_dir):
    assert (await checks("gated_srv"))[0] == "The corpus alpha is not marked ready."
    (run_dir / "alpha.ready").touch()
    assert (await checks("gated_srv"))[0] is None


async def test_a_check_that_cannot_be_run_is_an_error_not_an_unmet_check(checks):
    with pytest.raises(CheckError) as e:
        await checks("gated_missing")
    assert str(e.value) == "the precondition check for `gated_missing` could not be run: no tool `nosuchtool`"
    with pytest.raises(CheckError, match="broken_check raised RuntimeError: the readiness file is unreadable"):
        await checks("gated_broken")


class Stub:
    """A tool source whose every tool answers as told."""

    def __init__(self, answer):
        self.answer, self.calls = answer, []

    async def call(self, name, args, state):
        self.calls.append((name, args, dict(state)))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer(state) if callable(self.answer) else self.answer


def stubbed(instance, *checks, answers):
    node = dataclasses.replace(instance.nodes["refresh"], preconditions=tuple(checks))
    tools = {name: (source, ToolSpec(name, "", {})) for name, source in answers.items()}
    return node, tools


async def run_stubbed(node, tools, *, functions=(), inputs=None, facts=None):
    return await unmet_precondition(
        node, inputs or {}, facts or {}, tools=tools, functions=set(functions), fill=lambda text: text.upper()
    )


async def test_a_later_check_sees_what_an_earlier_one_wrote(instance):
    def writes(state):
        state["seen"] = 1
        return True

    def reads(state):
        return "seen" in state

    node, tools = stubbed(
        instance,
        {"tool": "a", "message": "m"},
        {"tool": "b", "message": "later did not see it"},
        answers={"a": Stub(writes), "b": Stub(reads)},
    )
    assert await run_stubbed(node, tools, functions={"a", "b"}) == (None, [("seen", 1)])


async def test_the_checks_see_the_facts_and_inputs_but_do_not_change_them(instance):
    def reads(state):
        state["sources"] = "changed"
        return state["branch"] == "main" and state["sources"] == "changed"

    node, tools = stubbed(instance, {"tool": "a", "message": "m"}, answers={"a": Stub(reads)})
    facts, inputs = {"branch": "main"}, {"sources": "x"}
    message, wrote = await run_stubbed(node, tools, functions={"a"}, inputs=inputs, facts=facts)
    assert message is None and wrote == [("sources", "changed")]
    assert facts == {"branch": "main"} and inputs == {"sources": "x"}


async def test_the_first_unmet_check_ends_the_checking_and_its_message_is_filled(instance):
    stop = Stub(False)
    node, tools = stubbed(
        instance,
        {"tool": "a", "args": {"x": "text", "n": 3}, "message": "unmet"},
        {"tool": "b", "message": "never"},
        answers={"a": Stub("false"), "b": stop},
    )
    assert await run_stubbed(node, tools) == ("UNMET", [])
    assert tools["a"][0].calls == [("a", {"x": "TEXT", "n": 3}, {})]  # strings are filled, other values kept
    assert stop.calls == []


async def test_a_server_tool_with_a_result_that_is_not_json_is_met(instance):
    node, tools = stubbed(instance, {"tool": "a", "message": "m"}, answers={"a": Stub("all good")})
    assert await run_stubbed(node, tools) == (None, [])


async def test_a_shell_result_with_a_nonzero_exit_is_unmet(instance):
    node, tools = stubbed(instance, {"tool": "a", "message": "m"}, answers={"a": Stub('{"exit": 1, "stdout": ""}')})
    assert await run_stubbed(node, tools) == ("M", [])


async def test_a_tool_that_says_it_failed_or_is_unreachable_is_a_check_that_cannot_be_run(instance):
    for error in (ToolError("it said no"), ToolServerError("no server")):
        node, tools = stubbed(instance, {"tool": "a", "message": "m"}, answers={"a": Stub(error)})
        with pytest.raises(CheckError, match=r"^the precondition check for `refresh` could not be run: "):
            await run_stubbed(node, tools)
