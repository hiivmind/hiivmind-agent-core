"""Function tools: plain Python functions the instance declares (`tools:` in instance.yaml).

A declared function may take `settings` and `state`; the harness fills both and the model never sees them (TOOL-12).
"""

import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from pydantic import BaseModel, create_model

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


_NAMED = ("properties", "patternProperties", "$defs")  # maps of name to subschema: the names are not keywords
_VALUES = ("default", "const", "enum", "examples")  # instance values, not subschemas


def _untitled(schema: object) -> object:
    if isinstance(schema, list):
        return [_untitled(s) for s in schema]
    if not isinstance(schema, dict):
        return schema
    out = {}
    for key, value in schema.items():
        if key == "title":
            continue
        if key in _NAMED and isinstance(value, dict):
            out[key] = {name: _untitled(sub) for name, sub in value.items()}
        elif key in _VALUES:
            out[key] = value
        else:
            out[key] = _untitled(value)
    return out


def tool_schema(model: type[BaseModel]) -> dict:
    """The JSON schema a tool is offered with: the model's, without pydantic's titles (Q2). A property named
    `title` stays; only the `title` keyword of each schema object goes."""
    return _untitled(model.model_json_schema())


def describe(fn: Callable, name: str | None = None) -> FunctionTool:
    """The tool of `fn`: its schema from its type hints, without the parameters the harness fills."""
    name = name or fn.__name__
    parameters = inspect.signature(fn).parameters
    shown = {
        n: (Any if p.annotation is p.empty else p.annotation, ... if p.default is p.empty else p.default)
        for n, p in parameters.items()
        if n not in FILLED
    }
    spec = ToolSpec(name, inspect.getdoc(fn) or name, tool_schema(create_model(name, **shown)))
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
