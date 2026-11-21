import json
import subprocess
import sys

import pytest
from cli_support import ALPHA, FIXTURES, REPO

from agent_core.cli import main

TOY = FIXTURES / "instance" / "instance.yaml"


def run_cli(tmp_path, capsys):
    instance = TOY
    code = main(["job", str(instance), "plain_run", "--settings", str(ALPHA), "--backend", "langgraph",
                 "--run-dir", str(tmp_path / "run")])
    return code, capsys.readouterr().out.splitlines()[-1]


def test_a_missing_provider_extra_stops_the_run_before_it_starts(monkeypatch, tmp_path, capsys):    # MOD-3, example 5
    monkeypatch.setenv("AGENT_CORE_LANGGRAPH_MODEL", "openai:gpt-6-luna")
    import importlib.util

    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: None if name == "langchain_openai" else real(name, *a))
    assert run_cli(tmp_path, capsys) == (
        2, "error: the model provider openai needs the extra agent-core[openai], which is not installed",
    )


@pytest.mark.parametrize("model", ["claude-haiku-5-5", "mistral:large", ":x", "anthropic:"])
def test_a_model_setting_without_a_known_provider_stops_the_run_before_it_starts(monkeypatch, tmp_path, capsys, model):  # Review Focus 1
    monkeypatch.setenv("AGENT_CORE_LANGGRAPH_MODEL", model)
    assert run_cli(tmp_path, capsys) == (
        2, "error: the setting MODEL must be `provider:model` with a provider of: anthropic, openai",
    )


def test_the_backend_imports_only_the_chosen_providers_package(tmp_path):    # absorbed record 30
    (tmp_path / "plain.json").write_text(json.dumps([]))
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(REPO / 'tests' / 'conformance')!r})\n"
        "import script_model, agent_core\n"
        f"agent_core.open({str(TOY)!r}, backend='langgraph', settings=[{str(ALPHA)!r}])\n"
        "bad = [m for m in ('anthropic', 'openai', 'langchain_anthropic', 'langchain_openai') if m in sys.modules]\n"
        "assert not bad, bad\n"
    )
    ran = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=REPO, timeout=120,
        env={**__import__("os").environ, "AGENT_CORE_LANGGRAPH_MODEL": f"script:{tmp_path}"},
    )
    assert ran.returncode == 0, ran.stderr


def test_a_chosen_provider_whose_package_is_installed_is_resolved_lazily():
    from agent_core.backends.langgraph.providers import PROVIDER_MODULES

    assert PROVIDER_MODULES == {
        "anthropic": "agent_core.backends.langgraph.providers.anthropic",
        "openai": "agent_core.backends.langgraph.providers.openai",
    }


E6 = "CREDENTIAL=account needs mountainash-auth-openai: install agent-core with the extra `openai`."


def test_account_without_the_package_stops_the_run_before_it_starts(monkeypatch):    # E6, CRED-18
    import importlib.util

    from agent_core.backends.langgraph.backend import LangGraphBackend
    from agent_core.backends.langgraph.settings import LangGraphSettings
    from agent_core.contracts.errors import RunCannotStart

    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: None if name == "mountainash_auth_openai" else real(name, *a))
    with pytest.raises(RunCannotStart) as stopped:
        LangGraphBackend(LangGraphSettings(MODEL="openai:gpt-6-luna", CREDENTIAL="account"))
    assert str(stopped.value) == E6
    LangGraphBackend(LangGraphSettings(MODEL="openai:gpt-6-luna", CREDENTIAL="env"))   # env needs no sign-in package
