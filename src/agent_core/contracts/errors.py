class ToolError(Exception):
    """A tool said the call failed."""


class ToolServerError(Exception):
    """A tool could not be reached."""


class ProviderUnavailable(Exception):
    """The model provider refused a call (429), failed (5xx) or could not be reached, after the client's own retries."""
