import json

import pytest

from agent_core.backends.scripted import ScriptedBackend, ScriptedSettings
from agent_core.contracts import Brief, RunEnd

BRIEF = Brief(instructions="# Procedure of the node that is running: `refresh`\n", tools=(), handover=(), opening="go")


def brief_for(node: str) -> Brief:
    return Brief(
        instructions=f"intro\n# Procedure of the node that is running: `{node}`\nbody\n", tools=(), handover=(), opening="go"
    )


async def test_reports_each_response_before_its_calls_and_stops_when_told(recorder):  # KIT-5, KIT-6
    end = await ScriptedBackend(script=[[["a", {}], ["b", {}]], [["exit", {}]], [["never", {}]]]).drive(
        BRIEF, recorder.ending_on("exit")
    )
    assert recorder.events == [
        ("responded", ("a", "b")),
        ("handle", "a"),
        ("handle", "b"),
        ("responded", ("exit",)),
        ("handle", "exit"),
    ]
    assert end == RunEnd(by_controller=True, said="")


async def test_a_string_step_is_the_model_stopping(recorder):  # KIT-10
    end = await ScriptedBackend(script=["READY?", [["exit", {}]]]).drive(BRIEF, recorder.replying("go on").ending_on("exit"))
    assert recorder.events[:2] == [("responded", ()), ("stopped", "READY?")] and end.by_controller
    end = await ScriptedBackend(script=["I cannot."]).drive(BRIEF, type(recorder)().replying(None))
    assert end == RunEnd(by_controller=False, said="I cannot.")


async def test_a_response_carries_its_text_its_calls_and_no_counts(recorder):
    await ScriptedBackend(script=["hello", [["a", {"x": 1}]]]).drive(BRIEF, recorder.replying("more").ending_on("a"))
    response = recorder.last_response
    assert [(c.name, c.args) for c in response.calls] == [("a", {"x": 1})]
    assert response.calls[0].id
    assert (response.sent, response.cache_read, response.cache_written) == (None, None, None)


async def test_the_script_running_out_without_an_end_is_the_model_stopping_with_nothing_said(recorder):
    end = await ScriptedBackend(script=[[["a", {}]]]).drive(BRIEF, recorder)
    assert end == RunEnd(by_controller=False, said="")


async def test_the_script_file_is_chosen_by_the_node_named_in_the_briefs_procedure_line(tmp_path, recorder):  # R6, R7
    (tmp_path / "refresh.json").write_text(json.dumps([[["from_refresh", {}]]]))
    (tmp_path / "other.json").write_text(json.dumps([[["from_other", {}]]]))
    backend = ScriptedBackend(ScriptedSettings(SCRIPTS=tmp_path))
    await backend.drive(brief_for("other"), recorder)
    assert recorder.events == [("responded", ("from_other",)), ("handle", "from_other")]


async def test_the_scripts_directory_is_read_from_the_environment(tmp_path, monkeypatch, recorder):
    (tmp_path / "refresh.json").write_text(json.dumps([[["x", {}]]]))
    monkeypatch.setenv("AGENT_CORE_SCRIPTED_SCRIPTS", str(tmp_path))
    from agent_core.core.registry import backend

    cls, settings_cls = backend("scripted")
    await cls(settings_cls()).drive(brief_for("refresh"), recorder)
    assert recorder.events[1] == ("handle", "x")


async def test_a_missing_script_file_names_the_file(tmp_path, recorder):
    with pytest.raises(FileNotFoundError, match="refresh.json"):
        await ScriptedBackend(ScriptedSettings(SCRIPTS=tmp_path)).drive(brief_for("refresh"), recorder)


async def test_without_a_script_or_directory_the_backend_says_so(recorder):
    with pytest.raises(ValueError, match="SCRIPTS"):
        await ScriptedBackend(ScriptedSettings()).drive(BRIEF, recorder)


async def test_instructions_without_the_procedure_line_are_refused(tmp_path, recorder):
    brief = Brief(instructions="no line here", tools=(), handover=(), opening="")
    with pytest.raises(ValueError, match="Procedure of the node that is running"):
        await ScriptedBackend(ScriptedSettings(SCRIPTS=tmp_path)).drive(brief, recorder)
