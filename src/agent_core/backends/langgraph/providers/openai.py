"""The OpenAI provider module: `MODEL=openai:<model>`. The only file of the backend that imports `openai`, and the only
one that imports `mountainash_auth_openai`, on the `CREDENTIAL=account` path only (CRED-16)."""

import importlib.util
from typing import Literal

import openai
from langchain.agents.middleware import AgentMiddleware
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage

from agent_core.backends.langgraph.settings import LangGraphSettings
from agent_core.contracts.errors import RunCannotStart
from agent_core.contracts.values import Usage

name = "openai"
packages = ("langchain_openai", "openai")

GLOSS = {"insufficient_quota": "no credit"}


APPLICATION = "hiivmind-agent-core"   # every instance shares the one sign-in (credentials design, decision 7)
ACCOUNT_PACKAGE = "mountainash_auth_openai"


def check(settings: LangGraphSettings) -> None:
    """`CREDENTIAL=account` needs the sign-in package; without it the run stops before it starts (E6, CRED-18)."""
    if settings.CREDENTIAL == "account" and importlib.util.find_spec(ACCOUNT_PACKAGE) is None:
        raise RunCannotStart("CREDENTIAL=account needs mountainash-auth-openai: install agent-core with the extra `openai`.")


def chat_model(model: str, settings: LangGraphSettings) -> BaseChatModel:
    if settings.CREDENTIAL == "account":
        return _subscription_model(model)
    return init_chat_model(f"openai:{model}", max_tokens=settings.MAX_TOKENS, max_retries=0)   # the retry middleware is the one owner (MOD-6)


def _subscription_model(model: str) -> BaseChatModel:
    """The ChatGPT subscription route (CRED-15): the Responses API, streamed, not stored, no output cap and no
    temperature, and the signed-in account's token, asked for each request, as the key."""
    from langchain_openai import ChatOpenAI
    from mountainash_auth_openai import ROUTE, OpenAIAccounts

    accounts = OpenAIAccounts.open(APPLICATION)
    return ChatOpenAI(
        model=model, base_url=ROUTE.base_url, use_responses_api=True, streaming=ROUTE.stream, store=ROUTE.store,
        max_retries=0, api_key=accounts.token,
    )


def _code(error: BaseException) -> str | None:
    code = getattr(error, "code", None)
    return code if isinstance(code, str) else None


def classify(error: BaseException) -> Literal["passes", "will not pass", "other"]:
    if isinstance(error, openai.RateLimitError):
        return "will not pass" if _code(error) == "insufficient_quota" else "passes"   # no credit does not come back by waiting
    if isinstance(error, (openai.InternalServerError, openai.APIConnectionError)):
        return "passes"
    return "other"


def refusal(error: BaseException) -> str:
    code = _code(error) or "unknown"
    gloss = GLOSS.get(code)
    return f"the provider refused: {code} ({gloss})" if gloss else f"the provider refused: {code}"


def cache_middleware() -> list[AgentMiddleware]:
    return []   # OpenAI caches a long enough prefix by itself


def usage(message: AIMessage) -> Usage:
    meta = message.usage_metadata
    if not meta:
        return Usage()
    details = meta.get("input_token_details") or {}
    return Usage(meta.get("input_tokens"), details.get("cache_read"), None)   # OpenAI does not report what it wrote
