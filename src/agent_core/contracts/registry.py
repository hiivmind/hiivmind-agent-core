"""Decorators a provider uses to register itself, and what they registered.

Standard library only: a provider imports this module, never the core.
"""

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

