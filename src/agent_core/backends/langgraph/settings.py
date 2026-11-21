from typing import Literal

from mountainash_settings import MountainAshBaseSettings
from pydantic import Field
from pydantic_settings import SettingsConfigDict


class LangGraphSettings(MountainAshBaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENT_CORE_LANGGRAPH_")

    MODEL: str                  # `provider:model`; there is no default (P20)
    MAX_TOKENS: int = Field(
        16000,
        description="The cap on each reply's output tokens on an API-key route. The ChatGPT subscription route "
        "(CREDENTIAL=account with an openai MODEL) applies no output-token cap: it refuses one (CRED-22).",
    )
    RECURSION_LIMIT: int = 120
    MAX_RETRIES: int = 8        # RTY-1
    CREDENTIAL: Literal["env", "account"] = "env"   # how the provider's code obtains its credential (CRED-13)
