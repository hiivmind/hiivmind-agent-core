"""MCP stdio server for the spike: a server that is down until the file web.up exists in the run directory.

While it is down, a call to `fetch` ends the server process in the middle of the call.
"""
import json
import os
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP

RUN_DIR = Path(os.environ["AGENT_CORE_RUN_DIR"])
mcp = FastMCP("spike-web")


def record(tool: str, args: dict) -> None:
    line = {"ts": time.time(), "server_pid": os.getpid(), "server": "web", "tool": tool, "args": args}
    with (RUN_DIR / "tool_calls.jsonl").open("a") as f:
        f.write(json.dumps(line) + "\n")


@mcp.tool()
def fetch(url: str) -> str:
    """Fetch a page."""
    record("fetch", {"url": url})
    if not (RUN_DIR / "web.up").exists():
        os._exit(1)  # the server dies during the call
    return f"fetched {url}"


@mcp.tool()
def note(text: str) -> str:
    """Keep a note on the web server. The other server has a tool of the same name."""
    record("note", {"text": text})
    return "noted on web"


if __name__ == "__main__":
    mcp.run()
