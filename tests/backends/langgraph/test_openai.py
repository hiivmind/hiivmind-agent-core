"""The OpenAI provider module, offline."""

import httpx
import openai
import pytest
from langchain_core.messages import AIMessage

from agent_core.backends.langgraph.providers import openai as module
from agent_core.backends.langgraph.settings import LangGraphSettings
from agent_core.contracts.values import Usage

REQUEST = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")


def status_error(cls, status, code=None):
    body = {"message": "said no", "type": "x", "code": code} if code else None
    return cls("said no", response=httpx.Response(status, request=REQUEST), body=body)


def test_insufficient_quota_will_not_pass_and_says_why():                    # example 4, MOD-5
    e = status_error(openai.RateLimitError, 429, "insufficient_quota")
    assert (module.classify(e), module.refusal(e)) == ("will not pass", "the provider refused: insufficient_quota (no credit)")


@pytest.mark.parametrize("error, kind", [
    (status_error(openai.RateLimitError, 429, "rate_limit_exceeded"), "passes"),
    (status_error(openai.RateLimitError, 429), "passes"),
    (status_error(openai.InternalServerError, 503), "passes"),
    (openai.APIConnectionError(request=REQUEST), "passes"),
    (status_error(openai.BadRequestError, 400), "other"),
    (ValueError("x"), "other"),
])
def test_what_passes_and_what_is_not_a_refusal(error, kind):
    assert module.classify(error) == kind


def test_openai_has_no_cache_middleware_and_does_not_report_cache_writes():
    assert module.cache_middleware() == []
    message = AIMessage("ok")
    message.usage_metadata = {"input_tokens": 9, "output_tokens": 1, "total_tokens": 10, "input_token_details": {"cache_read": 4}}
    assert module.usage(message) == Usage(9, 4, None)
    assert module.usage(AIMessage("ok")) == Usage()


def test_the_client_does_not_retry_and_the_reply_limit_is_the_setting(monkeypatch):    # MOD-6
    monkeypatch.setenv("OPENAI_API_KEY", "not-used")
    model = module.chat_model("gpt-6-luna", LangGraphSettings(MODEL="openai:gpt-6-luna", MAX_RETRIES=8, MAX_TOKENS=1234))
    assert model.max_retries == 0
    assert model.max_tokens == 1234
