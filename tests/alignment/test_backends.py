import importlib.util
import inspect

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
