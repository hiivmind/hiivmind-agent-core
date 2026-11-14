from mountainash_settings import MountainAshBaseSettings
from pydantic_settings import SettingsConfigDict


class LangGraphSettings(MountainAshBaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENT_CORE_LANGGRAPH_")

    MODEL: str = "claude-sonnet-5-5"
    MAX_TOKENS: int = 2000
    RECURSION_LIMIT: int = 120
