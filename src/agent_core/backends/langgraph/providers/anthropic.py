"""The Anthropic provider module: `MODEL=anthropic:<model>`. The only file of the backend that imports `anthropic`."""

from typing import Literal

import anthropic
from langchain.agents.middleware import AgentMiddleware
from langchain.chat_models import init_chat_model
from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage

from agent_core.backends.langgraph.settings import LangGraphSettings
from agent_core.contracts.errors import ProviderRefused
from agent_core.contracts.values import Usage

name = "anthropic"
packages = ("langchain_anthropic", "anthropic")


def check(settings: LangGraphSettings) -> None:
    return None   # nothing to check before the run: CREDENTIAL=account is refused at the node run (E5, CRED-17)


def chat_model(model: str, settings: LangGraphSettings) -> BaseChatModel:
    if settings.CREDENTIAL == "account":   # Anthropic has no signed-in account: refused before any model call (E5, CRED-17)
        raise ProviderRefused("the provider anthropic has no signed-in account; set AGENT_CORE_LANGGRAPH_CREDENTIAL=env to use its key.")
    return init_chat_model(f"anthropic:{model}", max_tokens=settings.MAX_TOKENS, max_retries=0)   # the retry middleware is the one owner (MOD-6)


def classify(error: BaseException, settings: LangGraphSettings) -> Literal["passes", "will not pass", "other"]:
    """A refusal (429), a server error (5xx, 529 included) and a failed connection pass; anything else is not a refusal."""
    if isinstance(error, (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIConnectionError)):
        return "passes"
    return "other"


def refusal(error: BaseException, settings: LangGraphSettings) -> str:
    return f"the provider refused: {error}"   # no Anthropic error is classified `will not pass`


def cache_middleware() -> list[AgentMiddleware]:
    return [AnthropicPromptCachingMiddleware()]


def usage(message: AIMessage) -> Usage:
    """What the response reports; a count it does not report is `None`, never zero (KIT-5)."""
    meta = message.usage_metadata
    if not meta:
        return Usage()
    details = meta.get("input_token_details") or {}
    if "ephemeral_5m_input_tokens" in details or "ephemeral_1h_input_tokens" in details:
        # the SDK sets `cache_creation` to 0 beside a positive breakdown by lifetime: the breakdown is the count
        written = details.get("ephemeral_5m_input_tokens", 0) + details.get("ephemeral_1h_input_tokens", 0)
    else:
        written = details.get("cache_creation")
    return Usage(meta.get("input_tokens"), details.get("cache_read"), written)
