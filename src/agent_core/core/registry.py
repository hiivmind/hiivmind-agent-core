"""Providers and backends by name.

The core may not import a provider module, so the tables below hold module
names as strings; a module is imported on first use and registers itself
through the decorators in `agent_core.contracts.registry`.
"""

import importlib
from collections.abc import Sequence
from pathlib import Path

from agent_core.contracts.loading import load_file
from agent_core.contracts.registry import REGISTERED, REGISTERED_BACKENDS

BACKENDS: dict[str, tuple[str, str]] = {
    "langgraph": ("agent_core.backends.langgraph", "langchain"),
    "scripted": ("agent_core.backends.scripted", ""),
}
PROVIDERS: dict[str, dict[str, str]] = {
    "context": {"none": "agent_core.context.none"},
    "tool_source": {
        "servers": "agent_core.tools.mcp_server",
        "tools": "agent_core.tools.function",
    },
    "resources": {"folder": "agent_core.resources.folder"},
    "store": {"memory": "agent_core.stores.memory"},
    "person": {
        "terminal": "agent_core.person.terminal",
        "nobody": "agent_core.person.nobody",
    },
}


class UnknownBackend(ValueError):
    pass


class BackendNotInstalled(RuntimeError):
    pass


class UnknownProvider(ValueError):
    pass


def backend(name: str) -> tuple[type, type]:
    if name in REGISTERED_BACKENDS:
        return REGISTERED_BACKENDS[name]
    if name not in BACKENDS:
        known = ", ".join(sorted(set(BACKENDS) | set(REGISTERED_BACKENDS)))
        raise UnknownBackend(f"no backend `{name}`; backends are: {known}")
    module, package = BACKENDS[name]
    try:
        importlib.import_module(module)
    except ModuleNotFoundError as e:
        raise BackendNotInstalled(
            f"backend `{name}` needs the package `{package or module}`, which is not installed"
        ) from e
    if name not in REGISTERED_BACKENDS:
        raise RuntimeError(f"module `{module}` did not register the backend `{name}`")
    return REGISTERED_BACKENDS[name]


def provider(kind: str, name: str) -> object:
    found = REGISTERED.get(kind, {})
    if name not in found and name in PROVIDERS.get(kind, {}):
        importlib.import_module(PROVIDERS[kind][name])
        found = REGISTERED.get(kind, {})
    if name not in found:
        known = ", ".join(sorted(set(PROVIDERS.get(kind, {})) | set(found)))
        raise UnknownProvider(f"no {kind} `{name}`; {kind}s are: {known}")
    return found[name]


def load_providers(root: Path, files: Sequence[str]) -> None:
    """Import each instance file by path; its decorators register it."""
    for file in files:
        load_file(root / file)
