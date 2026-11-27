from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .matrix import Entry, Feature


class ToolError(Exception):
    """A tool said the call failed."""


class ToolServerError(Exception):
    """A tool server could not be reached."""

    def __init__(self, server: str, tool: str, cause: object) -> None:
        self.server = server
        self.tool = tool
        super().__init__(f"tool server `{server}` did not answer the call to `{tool}`: {cause}")


class ProviderUnavailable(Exception):
    """The model provider refused a call, failed or could not be reached; a refusal that will pass."""


class ProviderRefused(Exception):
    """The model provider refused a call in a way that will not pass; not run again."""


class FeatureNotSupported(Exception):
    def __init__(self, feature: Feature, backend: str, entry: Entry) -> None:
        self.feature = feature
        self.backend = backend
        self.entry = entry
        super().__init__(f"{feature.title} is {entry.state} on backend {backend}: {entry.means}")


class RunCannotStart(Exception):
    """The one line `agent-core job` prints before exit 2."""


class SessionWaits(BaseException):
    """The person has gone: `hear` or `ask` gave None in a session. A `BaseException`, as `KeyboardInterrupt` is, so that
    nothing that catches `Exception` records it: the run that asked stops unrecorded, and the session saves and waits
    (SS-5). A backend lets it out of `run_node` and `run_fragment` as it was raised (SS-6)."""
