"""The OpenAI provider module: `MODEL=openai:<model>`. The only file of the backend that imports `openai`."""

from typing import Literal

import openai
from langchain.agents.middleware import AgentMiddleware
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage

from agent_core.backends.langgraph.settings import LangGraphSettings
from agent_core.contracts.values import Usage

name = "openai"
packages = ("langchain_openai", "openai")

GLOSS = {"insufficient_quota": "no credit"}


def check(settings: LangGraphSettings) -> None:
    return None


def chat_model(model: str, settings: LangGraphSettings) -> BaseChatModel:
    return init_chat_model(f"openai:{model}", max_tokens=settings.MAX_TOKENS, max_retries=0)   # the retry middleware is the one owner (MOD-6)


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
