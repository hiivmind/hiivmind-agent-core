"""The instance's settings object, built by the settings class the instance names."""

from collections.abc import Mapping, Sequence
from pathlib import Path

from pydantic import ValidationError

from agent_core.contracts.loading import load_module
from agent_core.core.instance import Instance


class SettingsError(ValueError):
    """The message names the fields that are missing or invalid, never a value."""


def _settings_class(instance: Instance, spec: str):
    module_path, dot, class_name = spec.rpartition(".")
    if not dot:
        raise SettingsError(f"settings.class `{spec}` must be `module.Class`, e.g. `settings.MySettings`")
    try:
        return getattr(load_module(instance.root, module_path), class_name)
    except Exception as e:  # no such file, no such class, or the file does not load
        raise SettingsError(f"settings.class `{spec}`: {_one_line(e)}") from e


def _one_line(e: Exception) -> str:
    return " ".join(f"{type(e).__name__}: {e}".split())


def load_settings(
    instance: Instance,
    extra_files: Sequence[Path] = (),
    params: Mapping[str, str] | None = None,
) -> object | None:
    """Layer the instance's files, then `extra_files`, then the environment, then `params`; None if the instance has no settings."""
    params = dict(params or {})
    if instance.settings is None:
        if params:
            raise SettingsError(f"settings: no setting named `{next(iter(params))}`")
        return None
    spec = instance.settings
    files = [str(instance.root / f) for f in spec.get("files", [])] + [str(Path(f).resolve()) for f in extra_files]
    cls = _settings_class(instance, spec["class"])
    for key in params:
        if key not in cls.model_fields:
            raise SettingsError(f"settings: no setting named `{key}`")
    try:
        return cls(config_files=files, env_prefix=spec.get("env_prefix"), **params)
    except ValidationError as e:
        fields = dict.fromkeys(".".join(str(p) for p in error["loc"]) or "(settings)" for error in e.errors())
        raise SettingsError(f"settings: missing or invalid: {', '.join(fields)}") from None
    except Exception as e:  # a settings file that is missing or cannot be read
        raise SettingsError(f"settings: {_one_line(e)}") from e
