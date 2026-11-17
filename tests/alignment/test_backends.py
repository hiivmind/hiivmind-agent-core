import importlib.util
import inspect

import pytest

from agent_core.contracts import NodeDriver
from agent_core.core.registry import BACKENDS, backend


def installed(package: str) -> bool:
    return importlib.util.find_spec(package) is not None


def test_each_backend_has_each_method_of_the_contract():  # TEST-1
    for name in BACKENDS:
        if name == "langgraph" and not installed("langchain"):
            continue
        cls, _ = backend(name)
        assert inspect.signature(cls.drive).parameters.keys() == inspect.signature(NodeDriver.drive).parameters.keys()
        assert inspect.iscoroutinefunction(cls.drive)


def test_the_langgraph_reply_limit_is_large_enough_for_a_long_exit_and_the_variable_sets_it(monkeypatch):   # review 4
    pytest.importorskip("langchain")
    _, settings = backend("langgraph")
    monkeypatch.delenv("AGENT_CORE_LANGGRAPH_MAX_TOKENS", raising=False)
    assert settings().MAX_TOKENS == 16000
    monkeypatch.setenv("AGENT_CORE_LANGGRAPH_MAX_TOKENS", "32000")
    assert settings().MAX_TOKENS == 32000


async def test_the_langgraph_client_retries_eight_times_by_default_and_the_variable_sets_it(monkeypatch):   # RTY-1
    pytest.importorskip("langchain")
    import agent_core.backends.langgraph.driver as driver

    cls, settings = backend("langgraph")
    monkeypatch.delenv("AGENT_CORE_LANGGRAPH_MAX_RETRIES", raising=False)
    assert settings().MAX_RETRIES == 8
    monkeypatch.setenv("AGENT_CORE_LANGGRAPH_MAX_RETRIES", "3")
    models = []

    class Stopped(Exception):
        pass

    def kept(model, **_):
        models.append(model)
        raise Stopped

    monkeypatch.setattr(driver, "create_agent", kept)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-used")
    brief = type("Brief", (), {"tools": (), "instructions": "", "handover": (), "opening": None})()
    with pytest.raises(Stopped):
        await cls(settings()).drive(brief, controller=None)
    assert models[0].max_retries == 3
