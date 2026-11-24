"""agent-core: `agent_core.open(instance)` returns the harness (architecture §4.2).

The names below are exposed lazily (module `__getattr__`), so that importing `agent_core.contracts.*` does not import
the core: the contracts are independent of it (LAYER-2).
"""

from importlib import import_module

_EXPORTS = {
    "FeatureNotSupported": "agent_core.contracts.errors",
    "RunCannotStart": "agent_core.contracts.errors",
    "ToolServerError": "agent_core.contracts.errors",
    "Outcome": "agent_core.contracts.values",
    "new_run_id": "agent_core.core.facade",
    "open": "agent_core.core.facade",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> object:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(_EXPORTS[name]), name)
    globals()[name] = value
    return value
