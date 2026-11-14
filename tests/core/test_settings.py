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
