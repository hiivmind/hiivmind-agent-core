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


ENV = LangGraphSettings(MODEL="openai:gpt-6-luna")
ACCOUNT = LangGraphSettings(MODEL="openai:gpt-6-luna", CREDENTIAL="account")


def test_insufficient_quota_will_not_pass_and_says_why():                    # example 4, MOD-5
    e = status_error(openai.RateLimitError, 429, "insufficient_quota")
    assert (module.classify(e, ENV), module.refusal(e, ENV)) == ("will not pass", "the provider refused: insufficient_quota (no credit)")


@pytest.mark.parametrize("error, kind", [
    (status_error(openai.RateLimitError, 429, "rate_limit_exceeded"), "passes"),
    (status_error(openai.RateLimitError, 429), "passes"),
    (status_error(openai.InternalServerError, 503), "passes"),
    (openai.APIConnectionError(request=REQUEST), "passes"),
    (status_error(openai.BadRequestError, 400), "other"),
    (ValueError("x"), "other"),
])
def test_what_passes_and_what_is_not_a_refusal(error, kind):
    assert module.classify(error, ENV) == kind


def account_cases():
    from mountainash_auth_openai import PlanPermissionRequired, RefreshFailed, Refusal, SignInRequired, reason

    nobody = SignInRequired("no OpenAI account is signed in for hiivmind-agent-core. Sign in: mountainash-auth-openai sign-in --application hiivmind-agent-core")
    no_plan = PlanPermissionRequired("owner@example.com has not allowed hiivmind-agent-core to use the ChatGPT plan.")
    refused = SignInRequired("OpenAI refused the sign-in of owner@example.com for hiivmind-agent-core (invalid_grant).", refused="invalid_grant")
    return [   # (error, classify, refusal text or None)
        (nobody, "will not pass", str(nobody)),                                                         # E3
        (no_plan, "will not pass", str(no_plan)),                                                       # E3b
        (refused, "will not pass", str(refused)),                                                       # E4
        (RefreshFailed("could not be refreshed; try again later."), "passes", None),
        (status_error(openai.RateLimitError, 429, "subscription_sharing_usage_limit_exceeded"), "will not pass", reason(Refusal.USAGE_LIMIT)),   # E7
        (status_error(openai.PermissionDeniedError, 403, "chatpass_v2_scope_not_authorized"), "will not pass", reason(Refusal.PERMISSION)),
        (status_error(openai.AuthenticationError, 401, "invalid_api_key"), "will not pass", reason(Refusal.SIGN_IN)),
        (ValueError("subscription_sharing_usage_limit_exceeded: limit reached"), "will not pass", reason(Refusal.USAGE_LIMIT)),   # a stream `error` event
        (ValueError("something else went wrong"), "other", None),
        (status_error(openai.RateLimitError, 429), "passes", None),                                     # E8, CRED-21
    ]


@pytest.mark.parametrize("case", range(10))
def test_refusals_on_the_account_path(case):    # CRED-19, CRED-20, CRED-21
    error, kind, text = account_cases()[case]
    assert module.classify(error, ACCOUNT) == kind
    if text is not None:
        assert module.refusal(error, ACCOUNT) == text


def test_an_env_run_keeps_its_meaning_after_an_account_client_was_built(accounts):    # Review Focus 2
    module.chat_model("gpt-6-luna", ACCOUNT)   # the sign-in package is now loaded in this process
    e = status_error(openai.AuthenticationError, 401, "invalid_api_key")
    assert module.classify(e, ENV) == "other"
    quota = status_error(openai.RateLimitError, 429, "insufficient_quota")
    assert (module.classify(quota, ENV), module.refusal(quota, ENV)) == ("will not pass", "the provider refused: insufficient_quota (no credit)")


def test_an_env_run_has_no_middleware_and_does_not_report_cache_writes():
    assert module.middleware(ENV) == []
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


async def test_a_token_call_that_raises_reaches_classify_as_itself(accounts):    # Review Focus 1, CRED-19
    from mountainash_auth_openai import PlanPermissionRequired

    accounts.token_error = PlanPermissionRequired("owner@example.com has not allowed hiivmind-agent-core to use the ChatGPT plan.")
    model = module.chat_model("gpt-6-luna", ACCOUNT)
    with pytest.raises(PlanPermissionRequired) as raised:   # the token call fails before any request is sent
        await model.ainvoke("hi")
    assert module.classify(raised.value, ACCOUNT) == "will not pass"


def test_the_backend_hands_its_settings_to_the_provider_for_a_plan_refusal(accounts):    # E7, CRED-20
    from mountainash_auth_openai import Refusal, reason

    from agent_core.backends.langgraph.backend import LangGraphBackend
    from agent_core.contracts.errors import ProviderRefused

    backend = LangGraphBackend(ACCOUNT)
    spent = status_error(openai.RateLimitError, 429, "subscription_sharing_usage_limit_exceeded")
    mapped = backend._mapped(spent)
    assert isinstance(mapped, ProviderRefused) and str(mapped) == reason(Refusal.USAGE_LIMIT)
    assert backend._retries().retry_on(spent) is False   # the retry middleware does not send it again (MOD-4)
    assert LangGraphBackend(ENV)._mapped(status_error(openai.AuthenticationError, 401, "invalid_api_key")).__class__ is openai.AuthenticationError


async def test_on_the_account_path_the_request_takes_the_routes_shape(accounts):    # ROUTE.accepts_system_messages, ROUTE.tools_strict_by_default
    from langchain.agents.middleware import ModelRequest
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_core.tools import StructuredTool

    schema = {"type": "object", "properties": {"path": {"type": "string"}, "head": {"type": "number"}, "tail": {"type": "number"}}, "required": ["path"]}
    read = StructuredTool(name="read_text_file", description="read a file", args_schema=schema, coroutine=lambda **_: "")
    model = module.chat_model("gpt-6-luna", ACCOUNT)
    [shapes] = module.middleware(ACCOUNT)
    request = ModelRequest(model=model, messages=[HumanMessage("go")], system_message=SystemMessage("Do the node."), tools=[read], model_settings={"x": 1})
    sent = []

    async def handler(request):
        sent.append(request)
        return AIMessage("ok")

    await shapes.awrap_model_call(request, handler)
    [request] = sent
    assert (request.system_message, request.model_settings) == (None, {"x": 1, "instructions": "Do the node.", "strict": False})
    bound = request.model.bind_tools(request.tools, **request.model_settings)   # as the agent binds them
    payload = model._get_request_payload(request.messages, **bound.kwargs)       # what ChatOpenAI sends
    assert payload["instructions"] == "Do the node."
    assert [item.get("role") for item in payload["input"]] == ["user"]
    assert [tool["strict"] for tool in payload["tools"]] == [False]   # an optional property stays optional
