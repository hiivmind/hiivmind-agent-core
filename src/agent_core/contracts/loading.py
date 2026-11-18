"""Load a Python file of an instance by path, once.

Standard library only: a provider imports this module, never the core. The same file always gives the same module
object. Its module name is private; the instance's directory is on `sys.path` while a run is open (see `open_run`), so the
files of an instance import each other by their own names.
"""

import errno
import hashlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def load_file(file: Path) -> ModuleType:
    """The module of the Python file `file`. `FileNotFoundError` when there is no such file; anything the file raises is raised."""
    file = Path(file).resolve()
    name = f"_agent_core_instance_{hashlib.sha256(str(file).encode()).hexdigest()[:16]}_{file.stem}"
    module = sys.modules.get(name)
    if module is None:
        if not file.is_file():
            raise FileNotFoundError(errno.ENOENT, "no such file", str(file))
        spec = importlib.util.spec_from_file_location(name, file)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load {file}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            del sys.modules[name]
            raise
    return module


def load_module(root: Path, dotted: str) -> ModuleType:
    """The module `dotted` (`tools.status`) of the instance directory `root`, loaded from `<root>/tools/status.py`."""
    return load_file(Path(root).joinpath(*dotted.split(".")).with_suffix(".py"))
