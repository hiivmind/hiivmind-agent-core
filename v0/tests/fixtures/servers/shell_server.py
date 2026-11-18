"""MCP stdio server for the spike: a shell tool, and a note tool that no node declares.

Every call is appended to $AGENT_CORE_RUN_DIR/tool_calls.jsonl by this process. That file is the
probes' record of which tool calls really ran, independent of the agent process.
"""
import json
import os
import subprocess
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP

RUN_DIR = Path(os.environ["AGENT_CORE_RUN_DIR"])
mcp = FastMCP("spike-tools")


def record(tool: str, args: dict) -> None:
    line = {"ts": time.time(), "server_pid": os.getpid(), "tool": tool, "args": args}
    with (RUN_DIR / "tool_calls.jsonl").open("a") as f:
        f.write(json.dumps(line) + "\n")


@mcp.tool()
def shell(command: str) -> str:
    """Run a shell command as the user and return its exit code and output."""
    record("shell", {"command": command})
    p = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=60, cwd=RUN_DIR)
    return json.dumps({"exit": p.returncode, "stdout": p.stdout[-4000:], "stderr": p.stderr[-2000:]})


@mcp.tool()
def note(text: str) -> str:
    """Append a note to the notes file."""
    record("note", {"text": text})
    with (RUN_DIR / "notes.txt").open("a") as f:
        f.write(text + "\n")
    return "noted"

@mcp.tool()
def lookup(key: str) -> str:
    """Look a key up in the corpus register. The register is empty, so every lookup fails inside this server."""
    record("lookup", {"key": key})
    raise ValueError(f"no such key: {key}")


@mcp.tool()
def ready(name: str) -> bool:
    """Say whether a corpus is marked ready: whether the file <name>.ready exists."""
    record("ready", {"name": name})
    return (RUN_DIR / f"{name}.ready").exists()


if __name__ == "__main__":
    mcp.run()
