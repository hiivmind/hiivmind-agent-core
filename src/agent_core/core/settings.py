"""The instance's settings object, built by the settings class the instance names."""

import importlib
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from pydantic import ValidationError

from agent_core.core.instance import Instance


class SettingsError(ValueError):
    """The message names the fields that are missing or invalid, never a value."""


def _settings_class(instance: Instance, spec: str):
    module_name, _, class_name = spec.rpartition(".")
    root = str(instance.root)
    if root not in sys.path:
        sys.path.insert(0, root)
    loaded = sys.modules.get(module_name)
    if loaded is not None and not str(getattr(loaded, "__file__", "")).startswith(root):
        del sys.modules[module_name]            # another instance's module of the same name
    return getattr(importlib.import_module(module_name), class_name)


def load_settings(
    instance: Instance,
    extra_files: Sequence[Path] = (),
    params: Mapping[str, str] | None = None,
) -> object | None:
    """Layer the instance's files, then `extra_files`, then the environment, then `params`; None if the instance has no settings."""
    if instance.settings is None:
        return None
    spec = instance.settings
    files = [str(instance.root / f) for f in spec.get("files", [])] + [str(Path(f).resolve()) for f in extra_files]
    cls = _settings_class(instance, spec["class"])
    try:
        return cls(config_files=files, env_prefix=spec.get("env_prefix"), **(params or {}))
    except ValidationError as e:
        fields = dict.fromkeys(".".join(str(p) for p in error["loc"]) or "(settings)" for error in e.errors())
        raise SettingsError(f"settings: missing or invalid: {', '.join(fields)}") from None
