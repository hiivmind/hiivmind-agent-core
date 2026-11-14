from pydantic import SecretStr

from mountainash_settings import MountainAshBaseSettings


class SpikeSettings(MountainAshBaseSettings):
    CORPUS_NAME: str
    CORPUS_PATH: str
    CORPUS_REPO: str
    BRANCH_PREFIX: str = "automated/refresh"
    GITHUB_TOKEN: SecretStr = SecretStr("not-a-real-token")
