"""Tool source for plain Python functions the instance declares (`tools:` in instance.yaml).

A declared function may take `settings` and `state`; the harness fills both and the model never sees them (TOOL-12).
"""

import inspect
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import create_model

from agent_core.contracts.loading import load_module
from agent_core.contracts.registry import register
from agent_core.contracts.values import ToolSpec

FILLED = ("settings", "state")


def _import(root: Path, path: str) -> Callable:
    """`module:function`, the module being a file of the instance; one module object for each file."""
    module_path, _, function = path.partition(":")
    module = load_module(root, module_path)
    try:
        return getattr(module, function)
    except AttributeError:
        raise ImportError(f"the module has no function `{function}`") from None


def _why(e: Exception) -> str:
    return " ".join(f"{type(e).__name__}: {e}".split())


@register("tool_source", "tools")
class FunctionSource:
    def __init__(self, declared: dict[str, str], settings: object | None, instance_root: Path):
        self._settings = settings
        self._function: dict[str, Callable] = {}
        self._filled: dict[str, tuple[str, ...]] = {}
        self._spec: dict[str, ToolSpec] = {}
        for name, path in declared.items():
            try:
                function = _import(instance_root, path)
            except Exception as e:  # a file that is missing, has no such function, does not parse or raises when loaded
                raise ValueError(f'instance.yaml: tool "{name}": cannot import {path}: {_why(e)}') from e
            try:
                parameters = inspect.signature(function).parameters
                shown = {
                    n: (Any if p.annotation is p.empty else p.annotation, ... if p.default is p.empty else p.default)
                    for n, p in parameters.items()
                    if n not in FILLED
                }
                schema = create_model(name, **shown).model_json_schema()
            except Exception as e:  # a signature the model cannot be shown
                raise ValueError(f'instance.yaml: tool "{name}": cannot describe {path}: {_why(e)}') from e
            schema.pop("title", None)
            self._function[name] = function
            self._filled[name] = tuple(n for n in FILLED if n in parameters)
            self._spec[name] = ToolSpec(name, inspect.getdoc(function) or name, schema)

    async def tools(self) -> tuple[ToolSpec, ...]:
        return tuple(self._spec.values())

    async def call(self, name: str, args: dict, state: dict) -> object:
        given = {"settings": self._settings, "state": state}
        return self._function[name](**args, **{n: given[n] for n in self._filled[name]})

    async def close(self) -> None:
        pass
