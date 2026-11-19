from pathlib import Path

import pytest

from agent_core.contracts.errors import RunCannotStart
from agent_core.core.functions import FunctionTool, describe, import_declared

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "instance"
DECLARED = {"count_words": "functions:count_words", "read_ledger": "functions:read_ledger", "locate": "functions:locate"}


@pytest.fixture
def tools():
    return {t.name: t for t in import_declared(FIXTURE, DECLARED)}


def test_function_tools_are_named_as_declared_with_the_docstring_for_description(tools):
    assert set(tools) == {"count_words", "read_ledger", "locate"}
    spec = tools["count_words"].spec
    assert spec.name == "count_words" and spec.description == "Count the words in a text."
    assert spec.schema == {
        "properties": {"text": {"title": "Text", "type": "string"}},
        "required": ["text"],
        "type": "object",
    }


def test_function_without_a_docstring_is_described_by_its_name():
    [tool] = import_declared(FIXTURE, {"never_ready": "checks:never_ready"})
    assert tool.spec.name == "never_ready" and tool.spec.description == "never_ready"
    assert tool.spec.schema["properties"] == {}


def test_function_schema_hides_settings_and_state(tools):                                # TOOL-12
    assert sorted(tools["locate"].spec.schema["properties"]) == ["source"]
    assert tools["locate"].filled == ("settings", "state")
    assert tools["read_ledger"].filled == ("state",)
    assert tools["count_words"].filled == ()


def test_describe_hides_settings_and_state_from_the_schema():
    def f(a: int, settings, state, b: str = "x"):
        """Doc."""

    tool = describe(f)
    assert isinstance(tool, FunctionTool) and tool.name == "f" and tool.fn is f
    assert tool.filled == ("settings", "state")
    assert sorted(tool.spec.schema["properties"]) == ["a", "b"] and tool.spec.schema["required"] == ["a"]
    assert describe(f, "other").name == "other" and describe(f, "other").spec.name == "other"


def test_function_returns_its_own_value(tools, monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_CORE_RUN_DIR", str(tmp_path))
    assert tools["count_words"].fn(text="one two three") == {"words": 3}


def test_function_that_raises_raises_its_own_exception(tools, monkeypatch, tmp_path):   # TOOL-11b
    monkeypatch.setenv("AGENT_CORE_RUN_DIR", str(tmp_path))
    with pytest.raises(FileNotFoundError, match="no ledger named main"):
        tools["read_ledger"].fn(name="main", state={})


def test_function_that_cannot_be_imported_names_the_tool():                              # TOOL-11d
    with pytest.raises(RunCannotStart) as e:
        import_declared(FIXTURE, {"missing": "functions:no_such_function"})
    assert str(e.value) == (
        'instance.yaml: tool "missing": cannot import functions:no_such_function: '
        "ImportError: the module has no function `no_such_function`"
    )


def test_function_in_a_module_that_does_not_exist_names_the_tool():
    with pytest.raises(RunCannotStart) as e:
        import_declared(FIXTURE, {"missing": "no_such_module:f"})
    assert str(e.value).startswith('instance.yaml: tool "missing": cannot import no_such_module:f: FileNotFoundError')
    assert "no_such_module.py" in str(e.value)


def test_function_file_that_does_not_parse_names_the_tool_and_the_error(tmp_path):    # a SyntaxError is not an ImportError
    (tmp_path / "broken.py").write_text("def f(:\n")
    with pytest.raises(RunCannotStart) as e:
        import_declared(tmp_path, {"broken": "broken:f"})
    assert str(e.value).startswith('instance.yaml: tool "broken": cannot import broken:f: SyntaxError')
    assert "\n" not in str(e.value)
