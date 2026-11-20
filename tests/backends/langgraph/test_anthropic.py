"""The Anthropic provider module, offline: errors built with an `httpx.Response`, as the SDK builds them."""

import anthropic
import httpx
import pytest
from langchain_core.messages import AIMessage

from agent_core.backends.langgraph.providers import anthropic as module
from agent_core.backends.langgraph.settings import LangGraphSettings
from agent_core.contracts.values import Usage

REQUEST = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def status_error(cls, status):
    return cls("said no", response=httpx.Response(status, request=REQUEST), body=None)


def answer(details=None, **meta) -> AIMessage:
    message = AIMessage("ok")
    if details is not None or meta:
        message.usage_metadata = {"input_tokens": 10, "output_tokens": 1, "total_tokens": 11, **meta}
        if details is not None:
            message.usage_metadata["input_token_details"] = details
    return message


def test_anthropic_cache_writes_are_zero_counted_or_not_reported():          # Review Focus 4
    zero = answer({"cache_read": 0, "cache_creation": 0})
    positive = answer({"cache_read": 5, "cache_creation": 0, "ephemeral_5m_input_tokens": 1000, "ephemeral_1h_input_tokens": 200})   # as langchain_anthropic normalises it
    unreported = answer({"cache_read": 5})
    assert [module.usage(m).cache_written for m in (zero, positive, unreported)] == [0, 1200, None]
    assert module.usage(answer({"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0})).cache_written == 0
    assert module.usage(answer({"cache_creation": 7})).cache_written == 7


def test_what_the_response_does_not_report_is_none_not_zero():
    assert module.usage(answer()) == Usage()
    assert module.usage(answer({})) == Usage(10, None, None)
    assert module.usage(answer({"cache_read": 3, "cache_creation": 4})) == Usage(10, 3, 4)


SETTINGS = LangGraphSettings(MODEL="anthropic:claude-haiku-5-5")


@pytest.mark.parametrize("cls, status, kind", [
    (anthropic.RateLimitError, 429, "passes"),
    (anthropic.InternalServerError, 500, "passes"),
    (anthropic.InternalServerError, 529, "passes"),
    (anthropic.BadRequestError, 400, "other"),
    (anthropic.AuthenticationError, 401, "other"),
])
def test_refusals_that_pass_are_the_rate_limit_server_and_connection_errors(cls, status, kind):
    assert module.classify(status_error(cls, status), SETTINGS) == kind


def test_a_dropped_connection_passes_and_a_plain_error_does_not():
    assert module.classify(anthropic.APIConnectionError(request=REQUEST), SETTINGS) == "passes"
    assert module.classify(ValueError("x"), SETTINGS) == "other"


def test_the_middleware_is_anthropics_prompt_caching():
    from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware

    [one] = module.middleware(SETTINGS)
    assert isinstance(one, AnthropicPromptCachingMiddleware)


def test_the_client_does_not_retry_and_the_reply_limit_is_the_setting(monkeypatch):    # MOD-6
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-used")
    model = module.chat_model("claude-haiku-5-5", LangGraphSettings(MODEL="anthropic:claude-haiku-5-5", MAX_RETRIES=8, MAX_TOKENS=1234))
    assert (model.max_retries, model.max_tokens) == (0, 1234)


E5 = "the provider anthropic has no signed-in account; set AGENT_CORE_LANGGRAPH_CREDENTIAL=env to use its key."


def test_account_is_refused_for_anthropic():    # E5, CRED-17
    from agent_core.contracts.errors import ProviderRefused

    with pytest.raises(ProviderRefused) as refused:
        module.chat_model("claude-haiku-5-5", LangGraphSettings(MODEL="anthropic:claude-haiku-5-5", CREDENTIAL="account"))
    assert str(refused.value) == E5


def test_account_on_anthropic_never_imports_the_sign_in_package():    # CRED-16, Review Focus 3
    import subprocess
    import sys

    code = (
        "import sys\n"
        "from agent_core.backends.langgraph.providers import anthropic as m\n"
        "from agent_core.backends.langgraph.settings import LangGraphSettings\n"
        "from agent_core.contracts.errors import ProviderRefused\n"
        "try:\n"
        "    m.chat_model('claude-haiku-5-5', LangGraphSettings(MODEL='anthropic:claude-haiku-5-5', CREDENTIAL='account'))\n"
        "except ProviderRefused:\n"
        "    pass\n"
        "assert 'mountainash_auth_openai' not in sys.modules\n"
    )
    ran = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
    assert ran.returncode == 0, ran.stderr


def test_env_is_unchanged_for_anthropic(monkeypatch):    # CRED-14
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-used")
    model = module.chat_model("claude-haiku-5-5", LangGraphSettings(MODEL="anthropic:claude-haiku-5-5"))
    assert (model.max_retries, model.max_tokens) == (0, 16000)
