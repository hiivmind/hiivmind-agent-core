"""The instance's settings object, built by the settings class the instance names."""

import hashlib
import importlib.util
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from pydantic import ValidationError

from agent_core.core.instance import Instance


class SettingsError(ValueError):
    """The message names the fields that are missing or invalid, never a value."""


def _settings_class(instance: Instance, spec: str):
    module_path, dot, class_name = spec.rpartition(".")
    if not dot:
        raise SettingsError(f"settings.class `{spec}` must be `module.Class`, e.g. `settings.MySettings`")
    root = instance.root.resolve()
    file = root.joinpath(*module_path.split(".")).with_suffix(".py")
    name = f"_agent_core_instance_{hashlib.sha256(str(root).encode()).hexdigest()[:16]}_{module_path.replace('.', '_')}"
    module = sys.modules.get(name)
    if module is None:
        module_spec = importlib.util.spec_from_file_location(name, file)
        module = importlib.util.module_from_spec(module_spec)
        sys.modules[name] = module
        try:
            module_spec.loader.exec_module(module)
        except BaseException:
            del sys.modules[name]
            raise
    return getattr(module, class_name)


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
