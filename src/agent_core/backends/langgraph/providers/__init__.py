"""Provider modules: what differs between model providers (architecture §4.7).

A provider module builds the chat model, classifies the errors of its SDK, gives its cache middleware and maps its
usage. A provider SDK is imported only by its own module, and a module is imported only when `MODEL` names it.
"""

import importlib
import importlib.util
from typing import Literal, Protocol

from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage

from agent_core.backends.langgraph.settings import LangGraphSettings
from agent_core.contracts.errors import RunCannotStart
from agent_core.contracts.registry import REGISTERED
from agent_core.contracts.values import Usage


class ProviderModule(Protocol):
    name: str                                   # "anthropic"
    packages: tuple[str, ...]                   # importable names its integration needs: ("langchain_anthropic", "anthropic")

    def check(self, settings: LangGraphSettings) -> None: ...   # raises RunCannotStart for settings it cannot run on
    def chat_model(self, model: str, settings: LangGraphSettings) -> BaseChatModel: ...   # max_retries=0 (MOD-6)
    def classify(self, error: BaseException, settings: LangGraphSettings) -> Literal["passes", "will not pass", "other"]: ...
    def refusal(self, error: BaseException, settings: LangGraphSettings) -> str: ...      # the text of a refusal that will not pass (MOD-5)
    def cache_middleware(self) -> list[AgentMiddleware]: ...
    def usage(self, message: AIMessage) -> Usage: ...


PROVIDER_MODULES: dict[str, str] = {
    "anthropic": "agent_core.backends.langgraph.providers.anthropic",
    "openai": "agent_core.backends.langgraph.providers.openai",
}
PROVIDER_PACKAGES: dict[str, tuple[str, ...]] = {   # what each named module needs, known without importing it
    "anthropic": ("langchain_anthropic", "anthropic"),
    "openai": ("langchain_openai", "openai"),
}


def provider_module(model_setting: str) -> tuple[ProviderModule, str]:
    """The provider module `MODEL` (`provider:model`) names, and the model's name. A provider that is registered
    (`register("model_provider", name)`) is used as it is; a named one is imported here, once its packages are found."""
    name, colon, model = model_setting.partition(":")
    registered = REGISTERED.get("model_provider", {})
    if not colon or not model or (name not in PROVIDER_MODULES and name not in registered):
        raise RunCannotStart(f"the setting MODEL must be `provider:model` with a provider of: {', '.join(sorted(PROVIDER_MODULES))}")
    if name in registered:
        module = registered[name]
        packages = module.packages
    else:
        module, packages = None, PROVIDER_PACKAGES[name]
    if any(importlib.util.find_spec(package) is None for package in packages):
        raise RunCannotStart(f"the model provider {name} needs the extra agent-core[{name}], which is not installed")
    if module is None:
        module = importlib.import_module(PROVIDER_MODULES[name])
    return module, model
