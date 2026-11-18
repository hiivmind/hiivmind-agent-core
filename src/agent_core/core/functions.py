"""Function tools: plain Python functions the instance declares (`tools:` in instance.yaml).

A declared function may take `settings` and `state`; the harness fills both and the model never sees them (TOOL-12).
"""

import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from pydantic import create_model

from agent_core.contracts.errors import RunCannotStart
from agent_core.contracts.loading import load_module
from agent_core.contracts.values import ToolSpec

FILLED = ("settings", "state")


@dataclass(frozen=True)
class FunctionTool:
    name: str
    spec: ToolSpec
    fn: Callable
    filled: tuple[str, ...]  # a subset of FILLED: the parameters the harness fills
    where: str = ""  # the declared `module:function`, for messages


def _why(e: Exception) -> str:
    return " ".join(f"{type(e).__name__}: {e}".split())


def describe(fn: Callable, name: str | None = None) -> FunctionTool:
    """The tool of `fn`: its schema from its type hints, without the parameters the harness fills."""
    name = name or fn.__name__
    parameters = inspect.signature(fn).parameters
    shown = {
        n: (Any if p.annotation is p.empty else p.annotation, ... if p.default is p.empty else p.default)
        for n, p in parameters.items()
        if n not in FILLED
    }
    schema = create_model(name, **shown).model_json_schema()
    schema.pop("title", None)
    spec = ToolSpec(name, inspect.getdoc(fn) or name, schema)
    return FunctionTool(name, spec, fn, tuple(n for n in FILLED if n in parameters))


def _import(root: Path, path: str) -> Callable:
    """`module:function`, the module being a file of the instance; one module object for each file."""
    module_path, _, function = path.partition(":")
    module = load_module(root, module_path)
    try:
        return getattr(module, function)
    except AttributeError:
        raise ImportError(f"the module has no function `{function}`") from None


def import_declared(root: Path, declared: Mapping[str, str]) -> list[FunctionTool]:
    tools = []
    for name, path in declared.items():
        try:
            fn = _import(root, path)
        except Exception as e:  # a file that is missing, has no such function, does not parse or raises when loaded
            raise RunCannotStart(f'instance.yaml: tool "{name}": cannot import {path}: {_why(e)}') from e
        try:
            tool = describe(fn, name)
        except Exception as e:  # a signature the model cannot be shown
            raise RunCannotStart(f'instance.yaml: tool "{name}": cannot describe {path}: {_why(e)}') from e
        tools.append(replace(tool, where=path))
    return tools
