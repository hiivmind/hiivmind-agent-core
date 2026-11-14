import pytest

from agent_core.contracts import registry as registered
from agent_core.core.registry import (
    BACKENDS,
    BackendNotInstalled,
    UnknownBackend,
    UnknownProvider,
    backend,
    load_providers,
    provider,
)


def test_unknown_backend_lists_the_known_ones():  # INST-1a
    with pytest.raises(UnknownBackend) as e:
        backend("langgrph")
    assert str(e.value) == "no backend `langgrph`; backends are: langgraph, scripted"


def test_backend_whose_package_is_missing_names_it(monkeypatch):  # INST-1b
    monkeypatch.setitem(BACKENDS, "openai", ("agent_core.backends.openai", "openai-agents"))
    with pytest.raises(BackendNotInstalled) as e:
        backend("openai")
    assert str(e.value) == "backend `openai` needs the package `openai-agents`, which is not installed"


@pytest.mark.xfail(strict=True, reason="Task 10")
def test_a_module_registers_itself_on_first_use():
    cls, settings = backend("scripted")
    assert isinstance(cls, type) and isinstance(settings, type)


def test_a_provider_in_the_instances_own_code_is_found(tmp_path, monkeypatch):
    monkeypatch.setitem(registered.REGISTERED, "tool_source", dict(registered.REGISTERED.get("tool_source", {})))
    (tmp_path / "echo.py").write_text(
        'from agent_core.contracts.registry import register\n@register("tool_source", "echo")\nclass Echo: ...\n'
    )
    load_providers(tmp_path, ["echo.py"])
    assert provider("tool_source", "echo").__name__ == "Echo"


def test_a_registered_backend_is_found_and_listed():
    class Settings: ...

    @registered.register_backend("mine", settings=Settings)
    class Mine: ...

    try:
        assert backend("mine") == (Mine, Settings)
        with pytest.raises(UnknownBackend) as e:
            backend("nope")
        assert str(e.value) == "no backend `nope`; backends are: langgraph, mine, scripted"
    finally:
        registered.REGISTERED_BACKENDS.pop("mine")


def test_unknown_provider_lists_the_known_ones():
    with pytest.raises(UnknownProvider) as e:
        provider("person", "termnal")
    assert str(e.value) == "no person `termnal`; persons are: nobody, terminal"
