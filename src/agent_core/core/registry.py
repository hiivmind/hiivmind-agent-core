"""Providers and backends by name.

The core may not import a provider or a helper module, so the tables below hold module names as strings; a module is
imported on first use and registers itself through the decorators in `agent_core.contracts.registry`.
"""

import importlib
from collections.abc import Mapping

from agent_core.contracts.registry import REGISTERED, REGISTERED_BACKENDS

BACKENDS: dict[str, tuple[str, str]] = {   # name -> (module, the package a missing module is blamed on; "" names the module)
    "scripted": ("agent_core.backends.scripted", ""),
}
PROVIDERS: dict[str, dict[str, str]] = {
    "walk": {"topology": "agent_core.helpers.walk"},
    "context": {"none": "agent_core.context.none"},
    "resources": {"folder": "agent_core.resources.folder"},
    "person": {
        "terminal": "agent_core.person.terminal",
        "nobody": "agent_core.person.nobody",
    },
    "journal": {
        "none": "agent_core.journals.none",
        "dbos": "agent_core.journals.dbos",
    },
}


class UnknownBackend(ValueError):
    pass


class BackendNotInstalled(RuntimeError):
    pass


class UnknownProvider(ValueError):
    pass


def backend(name: str, held: Mapping[str, tuple[type, type]] | None = None) -> tuple[type, type]:
    """The (backend class, settings class) of `name`. `held` is what the caller has registered itself: it hides the
    registry's backend of the same name."""
    found = {**REGISTERED_BACKENDS, **(held or {})}
    if name in found:
        return found[name]
    if name not in BACKENDS:
        known = ", ".join(sorted(set(BACKENDS) | set(found)))
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


def provider(kind: str, name: str, held: Mapping[str, object] | None = None) -> object:
    """The provider `name` of `kind`, its module imported on first use. `held` is what the caller has registered itself:
    it hides the registry's provider of the same name."""
    found = {**REGISTERED.get(kind, {}), **(held or {})}
    if name not in found and name in PROVIDERS.get(kind, {}):
        importlib.import_module(PROVIDERS[kind][name])
        found = {**REGISTERED.get(kind, {}), **(held or {})}
    if name not in found:
        known = ", ".join(sorted(set(PROVIDERS.get(kind, {})) | set(found)))
        raise UnknownProvider(f"no {kind} `{name}`; {kind}s are: {known}")
    return found[name]
