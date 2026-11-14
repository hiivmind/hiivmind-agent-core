import sys
import types
from dataclasses import replace

import pytest

from agent_core.core.settings import SettingsError, load_settings


def alpha(instance):
    return instance.root / "config" / "alpha.yaml"


def test_missing_required_setting_stops_and_names_the_field(instance):
    with pytest.raises(SettingsError) as e:
        load_settings(instance)
    assert "CORPUS_REPO" in str(e.value) and "base" not in str(e.value)     # the field, not the other values


def test_settings_file_layers_over_the_instances_own(instance):
    s = load_settings(instance, [alpha(instance)])
    assert (s.CORPUS_NAME, s.BRANCH_PREFIX, s.CORPUS_REPO) == ("alpha", "automated/refresh-base", "example/corpus-alpha")


def test_environment_beats_files_and_param_beats_environment(instance, monkeypatch):
    monkeypatch.setenv("SPIKE_CORPUS_REPO", "env/repo")
    assert load_settings(instance, [alpha(instance)]).CORPUS_REPO == "env/repo"
    assert load_settings(instance, [alpha(instance)], {"CORPUS_REPO": "cli/repo"}).CORPUS_REPO == "cli/repo"


def test_an_instance_without_settings_gives_none(instance):
    assert load_settings(replace(instance, settings=None)) is None


def test_the_error_names_every_missing_field_and_no_value(instance, monkeypatch):
    monkeypatch.setenv("SPIKE_CORPUS_NAME", "secret-name-value")
    monkeypatch.setenv("SPIKE_CORPUS_PATH", "/secret/path/value")
    with pytest.raises(SettingsError) as e:
        load_settings(instance)
    assert "CORPUS_REPO" in str(e.value)
    assert "secret" not in str(e.value) and "CORPUS_NAME" not in str(e.value)


def test_two_instances_each_get_their_own_settings_class_in_any_order(instance, tmp_path):
    def instance_with_class(name):
        root = tmp_path / name
        root.mkdir()
        (root / "settings.py").write_text(f"class Mine:\n    owner = {name!r}\n    def __init__(self, **kwargs): pass\n")
        return replace(instance, root=root, settings={"class": "settings.Mine", "files": []})

    a, b = instance_with_class("a"), instance_with_class("b")
    assert [load_settings(i).owner for i in (a, b, a)] == ["a", "b", "a"]


def test_loading_settings_leaves_other_modules_and_the_path_alone(instance, monkeypatch):
    before = list(sys.path)
    other = types.ModuleType("settings")
    monkeypatch.setitem(sys.modules, "settings", other)     # somebody else's `settings`
    load_settings(instance, [instance.root / "config" / "alpha.yaml"])
    assert sys.path == before and sys.modules["settings"] is other


def test_a_class_value_without_a_dot_is_a_settings_error_naming_it(instance):
    with pytest.raises(SettingsError, match="MySettings"):
        load_settings(replace(instance, settings={"class": "MySettings", "files": []}))
