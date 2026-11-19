"""The Anthropic provider module: `MODEL=anthropic:<model>`. The only file of the backend that imports `anthropic`."""

from typing import Literal

import anthropic
from langchain.agents.middleware import AgentMiddleware
from langchain.chat_models import init_chat_model
from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage

from agent_core.backends.langgraph.settings import LangGraphSettings
from agent_core.contracts.values import Usage

name = "anthropic"
packages = ("langchain_anthropic", "anthropic")


def chat_model(model: str, settings: LangGraphSettings) -> BaseChatModel:
    return init_chat_model(f"anthropic:{model}", max_tokens=settings.MAX_TOKENS, max_retries=0)   # the retry middleware is the one owner (MOD-6)


def classify(error: BaseException) -> Literal["passes", "will not pass", "other"]:
    """A refusal (429), a server error (5xx, 529 included) and a failed connection pass; anything else is not a refusal."""
    if isinstance(error, (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIConnectionError)):
        return "passes"
    return "other"


def refusal(error: BaseException) -> str:
    return f"the provider refused: {error}"   # no Anthropic error is classified `will not pass`


def cache_middleware() -> list[AgentMiddleware]:
    return [AnthropicPromptCachingMiddleware()]


def usage(message: AIMessage) -> Usage:
    """What the response reports; a count it does not report is `None`, never zero (KIT-5)."""
    meta = message.usage_metadata
    if not meta:
        return Usage()
    details = meta.get("input_token_details") or {}
    written = details.get("cache_creation")
    if written is None and ("ephemeral_5m_input_tokens" in details or "ephemeral_1h_input_tokens" in details):
        written = details.get("ephemeral_5m_input_tokens", 0) + details.get("ephemeral_1h_input_tokens", 0)
    return Usage(meta.get("input_tokens"), details.get("cache_read"), written)
