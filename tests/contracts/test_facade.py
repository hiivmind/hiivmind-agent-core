import importlib
import pkgutil

import agent_core.contracts as pkg


def test_every_contract_module_imports():
    for m in pkgutil.iter_modules(pkg.__path__):
        importlib.import_module(f"agent_core.contracts.{m.name}")
