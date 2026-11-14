"""Providers and backends by name.

The core may not import a provider module, so the tables below hold module
names as strings; a module is imported on first use and registers itself
through the decorators in `agent_core.contracts.registry`.
"""

import importlib
import importlib.util
import sys
from collections.abc import Sequence
from pathlib import Path

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
        path = (root / file).resolve()
        module_name = f"_agent_core_instance_{path.stem}_{abs(hash(path))}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load providers from {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            del sys.modules[module_name]
            raise
