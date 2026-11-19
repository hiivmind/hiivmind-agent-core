from mountainash_settings import MountainAshBaseSettings
from pydantic_settings import SettingsConfigDict


class LangGraphSettings(MountainAshBaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENT_CORE_LANGGRAPH_")

    MODEL: str                  # `provider:model`; there is no default (P20)
    MAX_TOKENS: int = 16000
    RECURSION_LIMIT: int = 120
    MAX_RETRIES: int = 8        # RTY-1
