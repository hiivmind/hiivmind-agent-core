"""Decorators a provider uses to register itself, and what they registered.

Standard library only: a provider imports this module, never the core.
"""

import importlib
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

REGISTERED_BACKENDS: dict[str, tuple[type, type]] = {}   # name -> (backend class, settings class)
REGISTERED: dict[str, dict[str, object]] = {}            # kind -> name -> provider


def register_backend(name: str, *, settings: type) -> Callable[[type], type]:
    def decorate(cls: type) -> type:
        REGISTERED_BACKENDS[name] = (cls, settings)
        return cls

    return decorate


def register(kind: str, name: str) -> Callable[[T], T]:
    def decorate(obj: T) -> T:
        REGISTERED.setdefault(kind, {})[name] = obj
        return obj

    return decorate


# Modules that register a provider, by (kind, name), as strings: a caller that may not import a provider asks `provider`.
MODULES: dict[tuple[str, str], str] = {
    ("walk", "topology"): "agent_core.helpers.walk",
    ("journal", "none"): "agent_core.journals.none",
    ("journal", "dbos"): "agent_core.journals.dbos",
}


def provider(kind: str, name: str) -> object:
    """The provider registered as `name` of `kind`; its module is imported on first use."""
    if name not in REGISTERED.get(kind, {}) and (kind, name) in MODULES:
        importlib.import_module(MODULES[kind, name])
    try:
        return REGISTERED[kind][name]
    except KeyError:
        known = ", ".join(sorted(REGISTERED.get(kind, {})))
        raise LookupError(f"no {kind} `{name}`; {kind}s are: {known}") from None
