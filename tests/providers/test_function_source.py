from pathlib import Path

import pytest

from agent_core.core.state import StateView
from agent_core.tools.function import FunctionSource

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "instance"


async def test_function_tools_are_named_as_declared_with_the_docstring_for_description(functions):
    specs = {t.name: t for t in await functions.tools()}
    assert set(specs) == {"count_words", "read_ledger", "locate"}
    assert specs["count_words"].description == "Count the words in a text."
    assert specs["count_words"].schema == {
        "properties": {"text": {"title": "Text", "type": "string"}},
        "required": ["text"],
        "type": "object",
    }


async def test_function_without_a_docstring_is_described_by_its_name():
    source = FunctionSource({"never_ready": "checks:never_ready"}, None, FIXTURE)
    [spec] = await source.tools()
    assert spec.name == "never_ready" and spec.description == "never_ready"
    assert spec.schema["properties"] == {}


async def test_function_schema_hides_settings_and_state(functions):                     # TOOL-12
    spec = {t.name: t for t in await functions.tools()}["locate"]
    assert sorted(spec.schema["properties"]) == ["source"]


async def test_function_returns_its_own_value(functions):
    assert await functions.call("count_words", {"text": "one two three"}, StateView()) == {"words": 3}


async def test_function_is_given_settings_and_state(functions):
    state = StateView({"source": "polars"})
    assert await functions.call("locate", {"source": "polars"}, state) == {"path": "/tmp/spike-corpus-alpha/polars"}
    assert {"path", "last_located"} <= state.written


async def test_function_that_raises_raises_its_own_exception(functions):                # TOOL-11b
    with pytest.raises(FileNotFoundError, match="no ledger named main"):
        await functions.call("read_ledger", {"name": "main"}, StateView())


def test_function_that_cannot_be_imported_names_the_tool():                              # TOOL-11d
    with pytest.raises(ValueError) as e:
        FunctionSource({"missing": "functions:no_such_function"}, None, FIXTURE)
    assert str(e.value) == (
        'instance.yaml: tool "missing": cannot import functions:no_such_function: '
        "ImportError: the module has no function `no_such_function`"
    )


def test_function_in_a_module_that_does_not_exist_names_the_tool():
    with pytest.raises(ValueError) as e:
        FunctionSource({"missing": "no_such_module:f"}, None, FIXTURE)
    assert str(e.value).startswith('instance.yaml: tool "missing": cannot import no_such_module:f: FileNotFoundError')
    assert "no_such_module.py" in str(e.value)


def test_function_file_that_does_not_parse_names_the_tool_and_the_error(tmp_path):    # a SyntaxError is not an ImportError
    (tmp_path / "broken.py").write_text("def f(:\n")
    with pytest.raises(ValueError) as e:
        FunctionSource({"broken": "broken:f"}, None, tmp_path)
    assert str(e.value).startswith('instance.yaml: tool "broken": cannot import broken:f: SyntaxError')
    assert "\n" not in str(e.value)
