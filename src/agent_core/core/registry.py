"""Providers by name.

The core may not import a provider or a helper module, so the table below holds module names as strings; a module is
imported on first use and registers itself through the decorators in `agent_core.contracts.registry`.
"""

import importlib

from agent_core.contracts.registry import REGISTERED

PROVIDERS: dict[str, dict[str, str]] = {
    "walk": {"topology": "agent_core.helpers.walk"},
    "journal": {"none": "agent_core.journals.none", "dbos": "agent_core.journals.dbos"},
}


def provider(kind: str, name: str) -> object:
    """The provider registered as `name` of `kind`, its module imported on first use. KeyError names an unknown one."""
    if name not in PROVIDERS.get(kind, {}) and name not in REGISTERED.get(kind, {}):
        raise KeyError(f"no {kind} `{name}`")
    if name not in REGISTERED.get(kind, {}):
        importlib.import_module(PROVIDERS[kind][name])
    return REGISTERED[kind][name]
