import pytest

from agent_core.contracts import registry as registered
from agent_core.core.registry import (
    BACKENDS,
    PROVIDERS,
    BackendNotInstalled,
    UnknownBackend,
    UnknownProvider,
    backend,
    provider,
)


def test_the_tables_name_the_backends_and_the_providers_of_v0():
    assert BACKENDS == {
        "scripted": ("agent_core.backends.scripted", ""),
        "langgraph": ("agent_core.backends.langgraph", "langchain"),
    }
    assert PROVIDERS == {
        "walk": {"topology": "agent_core.helpers.walk"},
        "context": {"none": "agent_core.context.none"},
        "resources": {"folder": "agent_core.resources.folder"},
        "person": {"terminal": "agent_core.person.terminal", "nobody": "agent_core.person.nobody"},
        "journal": {"none": "agent_core.journals.none", "dbos": "agent_core.journals.dbos"},
    }


def test_unknown_backend_lists_the_known_ones():  # INST-1a
    with pytest.raises(UnknownBackend) as e:
        backend("nope")
    assert str(e.value) == "no backend `nope`; backends are: langgraph, scripted"


def test_backend_whose_package_is_missing_names_it(monkeypatch):  # INST-1b
    monkeypatch.setitem(BACKENDS, "openai", ("agent_core.backends.openai", "openai-agents"))
    with pytest.raises(BackendNotInstalled) as e:
        backend("openai")
    assert str(e.value) == "backend `openai` needs the package `openai-agents`, which is not installed"


def test_a_backend_module_registers_itself_on_first_use(tmp_path, monkeypatch):
    (tmp_path / "fake_backend_module.py").write_text(
        "from agent_core.contracts.registry import register_backend\n"
        "class Settings: ...\n"
        "@register_backend('fake', settings=Settings)\n"
        "class Fake: ...\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setitem(BACKENDS, "fake", ("fake_backend_module", ""))
    try:
        cls, settings = backend("fake")
        assert (cls.__name__, settings.__name__) == ("Fake", "Settings")
    finally:
        registered.REGISTERED_BACKENDS.pop("fake", None)


def test_a_registered_backend_is_found_and_listed():
    class Settings: ...

    class Mine: ...

    registered.REGISTERED_BACKENDS["mine"] = (Mine, Settings)
    try:
        assert backend("mine") == (Mine, Settings)
        with pytest.raises(UnknownBackend) as e:
            backend("nope")
        assert str(e.value) == "no backend `nope`; backends are: langgraph, mine, scripted"
    finally:
        registered.REGISTERED_BACKENDS.pop("mine")


def test_a_backend_the_caller_holds_is_found_before_the_registry_and_listed():
    class Mine: ...

    local = {"scripted": (Mine, Mine), "mine": (Mine, Mine)}
    assert backend("scripted", local) == (Mine, Mine)
    with pytest.raises(UnknownBackend) as e:
        backend("nope", local)
    assert str(e.value) == "no backend `nope`; backends are: langgraph, mine, scripted"


def test_unknown_provider_lists_the_known_ones():
    with pytest.raises(UnknownProvider) as e:
        provider("person", "termnal")
    assert str(e.value) == "no person `termnal`; persons are: nobody, terminal"


def test_a_provider_module_registers_itself_on_first_use(tmp_path, monkeypatch):
    (tmp_path / "echo_person_module.py").write_text(
        "from agent_core.contracts.registry import register\n"
        "@register('person', 'echo')\n"
        "class Echo: ...\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setitem(PROVIDERS["person"], "echo", "echo_person_module")
    monkeypatch.setitem(registered.REGISTERED, "person", dict(registered.REGISTERED.get("person", {})))
    assert provider("person", "echo").__name__ == "Echo"


def test_a_provider_the_caller_holds_hides_the_registered_one_of_its_name():
    class Mine: ...

    class Other: ...

    assert provider("person", "mine", {"mine": Mine}) is Mine
    assert provider("person", "nobody", {"nobody": Other}) is Other
    with pytest.raises(UnknownProvider) as e:
        provider("person", "nope", {"mine": Mine})
    assert str(e.value) == "no person `nope`; persons are: mine, nobody, terminal"
