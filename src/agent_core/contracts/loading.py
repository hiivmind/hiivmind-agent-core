"""Load a Python file of an instance as a module of the instance's own package, once.

Standard library only: a provider imports this module, never the core. Each instance directory is one private package
(RP-3): its files are its modules, so they import each other relatively (`from .sources import X`), and two instances
that each have `tools/sources.py` get a module each. Nothing is put on `sys.path`. The same file always gives the same
module object.
"""

import errno
import hashlib
import importlib
import importlib.machinery
import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def instance_package(root: Path) -> str:
    """The name of the private package of the instance directory `root`, registered in `sys.modules` the first time."""
    root = Path(root).resolve()
    name = f"_agent_core_instance_{hashlib.sha256(str(root).encode()).hexdigest()[:16]}"
    if name not in sys.modules:
        spec = importlib.machinery.ModuleSpec(name, None, is_package=True)
        spec.submodule_search_locations = [str(root)]
        sys.modules[name] = importlib.util.module_from_spec(spec)
    return name


def load_module(root: Path, dotted: str) -> ModuleType:
    """The module `dotted` (`tools.status`) of the instance directory `root`, loaded from `<root>/tools/status.py`.
    `FileNotFoundError` when there is no such file; anything the file raises is raised."""
    file = Path(root).resolve().joinpath(*dotted.split(".")).with_suffix(".py")
    if not file.is_file():
        raise FileNotFoundError(errno.ENOENT, "no such file", str(file))
    return importlib.import_module(f"{instance_package(root)}.{dotted}")
