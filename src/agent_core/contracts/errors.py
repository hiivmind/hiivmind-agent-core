class ToolError(Exception):
    """A tool said the call failed."""


class ToolServerError(Exception):
    """A tool could not be reached."""
