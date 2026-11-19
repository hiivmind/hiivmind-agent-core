import pytest

import agent_core
from agent_core.contracts.errors import RunCannotStart

from cli_support import ALPHA, FIXTURES

TOY = FIXTURES / "instance" / "instance.yaml"


def test_model_has_no_default(monkeypatch):    # P20, TPL-6a, REG-5
    monkeypatch.delenv("AGENT_CORE_LANGGRAPH_MODEL", raising=False)
    with pytest.raises(RunCannotStart, match=r"settings: missing or invalid: MODEL"):
        agent_core.open(TOY, backend="langgraph", settings=[ALPHA])


def test_the_other_settings_have_their_defaults(monkeypatch):    # REG-5, RTY-1
    from agent_core.backends.langgraph.settings import LangGraphSettings

    monkeypatch.setenv("AGENT_CORE_LANGGRAPH_MODEL", "anthropic:claude-haiku-5-5")
    settings = LangGraphSettings()
    assert (settings.MODEL, settings.MAX_TOKENS, settings.RECURSION_LIMIT, settings.MAX_RETRIES) == (
        "anthropic:claude-haiku-5-5", 16000, 120, 8,
    )
