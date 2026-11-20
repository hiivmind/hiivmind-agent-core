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


def _account_refusal(error: BaseException) -> tuple[Literal["passes", "will not pass"], str] | None:
    """On the account path: the sign-in package's own errors, and the subscription route's refusals read through the
    package's table, from an HTTP status error or a streamed `error` event (`ValueError("<code>: <message>")`).
    `None` for anything the package does not name: today's rules then apply (CRED-19, CRED-20, CRED-21)."""
    from mountainash_auth_openai import PlanPermissionRequired, RefreshFailed, Refusal, SignInRequired, reason
    from mountainash_auth_openai import classify as route_refusal

    if isinstance(error, (SignInRequired, PlanPermissionRequired)):
        return "will not pass", str(error)   # the package's text names the account and the command to run
    if isinstance(error, RefreshFailed):
        return "passes", str(error)   # the sign-in is kept; a later call may pass
    if isinstance(error, openai.APIStatusError):
        refused = route_refusal(_code(error), error.status_code)
    elif isinstance(error, ValueError):
        code, colon, _ = str(error).partition(": ")
        refused = route_refusal(code, None) if colon else Refusal.OTHER
    else:
        return None
    return None if refused is Refusal.OTHER else ("will not pass", reason(refused))


def classify(error: BaseException, settings: LangGraphSettings) -> Literal["passes", "will not pass", "other"]:
    if settings.CREDENTIAL == "account" and (found := _account_refusal(error)) is not None:
        return found[0]
    if isinstance(error, openai.RateLimitError):
        return "will not pass" if _code(error) == "insufficient_quota" else "passes"   # no credit does not come back by waiting
    if isinstance(error, (openai.InternalServerError, openai.APIConnectionError)):
        return "passes"
    return "other"


def refusal(error: BaseException, settings: LangGraphSettings) -> str:
    if settings.CREDENTIAL == "account" and (found := _account_refusal(error)) is not None:
        return found[1]
    code = _code(error) or "unknown"
    gloss = GLOSS.get(code)
    return f"the provider refused: {code} ({gloss})" if gloss else f"the provider refused: {code}"


class _RouteShape(AgentMiddleware):
    """Each model call as the subscription route takes it (`ROUTE`): the node's instructions go as the Responses API's
    `instructions`, since a system message is refused; the tools go with `strict: false`, since a tool is otherwise
    strict and the model fills every optional property."""

    def __init__(self, route):
        super().__init__()
        self._route = route

    async def awrap_model_call(self, request, handler):
        settings, changes = dict(request.model_settings), {}
        if not self._route.accepts_system_messages and request.system_message is not None:
            settings["instructions"] = request.system_message.text
            changes["system_message"] = None
        if self._route.tools_strict_by_default and request.tools:
            settings["strict"] = False
        return await handler(request.override(model_settings=settings, **changes))


def middleware(settings: LangGraphSettings) -> list[AgentMiddleware]:
    """OpenAI caches a long enough prefix by itself. On the account path, the subscription route's facts shape each call."""
    if settings.CREDENTIAL != "account":
        return []
    from mountainash_auth_openai import ROUTE

    return [_RouteShape(ROUTE)]


def usage(message: AIMessage) -> Usage:
    meta = message.usage_metadata
    if not meta:
        return Usage()
    details = meta.get("input_token_details") or {}
    return Usage(meta.get("input_tokens"), details.get("cache_read"), None)   # OpenAI does not report what it wrote
