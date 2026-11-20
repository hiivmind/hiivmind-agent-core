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


class StandInAccounts:
    """`OpenAIAccounts` as the provider uses it: opened by application, an async token call. No file, no network."""

    opened: list[str] = []
    token_error: BaseException | None = None

    @classmethod
    def open(cls, application: str) -> "StandInAccounts":
        cls.opened.append(application)
        return cls()

    async def token(self) -> str:
        if StandInAccounts.token_error is not None:
            raise StandInAccounts.token_error
        return "stand-in"


@pytest.fixture
def accounts(monkeypatch):
    import mountainash_auth_openai

    StandInAccounts.opened = []
    StandInAccounts.token_error = None
    monkeypatch.setattr(mountainash_auth_openai, "OpenAIAccounts", StandInAccounts)
    return StandInAccounts


def test_env_builds_the_client_as_before(accounts, monkeypatch):    # CRED-14
    monkeypatch.setenv("OPENAI_API_KEY", "not-used")
    settings = LangGraphSettings(MODEL="openai:gpt-6-luna", MAX_TOKENS=1234)
    model = module.chat_model("gpt-6-luna", settings)
    assert (model.max_tokens, model.max_retries) == (1234, 0)
    assert accounts.opened == []


async def test_account_builds_the_subscription_client(accounts):    # CRED-15
    from langchain_openai import ChatOpenAI
    from mountainash_auth_openai import ROUTE

    model = module.chat_model("gpt-6-luna", LangGraphSettings(MODEL="openai:gpt-6-luna", CREDENTIAL="account"))
    assert isinstance(model, ChatOpenAI)
    assert model.use_responses_api is True
    assert model.streaming is ROUTE.stream
    assert model.store is ROUTE.store
    assert model.max_tokens is None and model.temperature is None
    assert model.max_retries == 0
    assert model.openai_api_base == ROUTE.base_url
    assert accounts.opened == ["hiivmind-agent-core"] == [module.APPLICATION]
    assert await model.openai_api_key() == "stand-in"
