"""An MCP stdio server with one tool, `run`: a shell command, run as the user, with no restriction (TOOL-8).

An instance declares it as `shell: {command: python, args: [-m, agent_tools.shell_server]}`; its tool is `shell__run`.
"""

import asyncio
import codecs
import os
import signal
from pathlib import Path
from typing import TypedDict

from mcp.server.fastmcp import FastMCP

LIMIT = 20_000  # characters kept of each of stdout and stderr: the last ones
CHUNK = 65_536
CLOSE_WAIT = 2  # seconds to let the output pipes drain after the command was ended

mcp = FastMCP("agent-tools-shell")


class Ran(TypedDict):
    exit: int
    stdout: str
    stderr: str
    cut: int


class _Tail:
    """The last `LIMIT` characters fed to it, and how many were dropped before them."""

    def __init__(self) -> None:
        self.text = ""
        self.cut = 0

    def feed(self, text: str) -> None:
        self.text += text
        if len(self.text) > LIMIT:
            self.cut += len(self.text) - LIMIT
            self.text = self.text[-LIMIT:]


async def _drain(stream: asyncio.StreamReader, tail: _Tail) -> None:
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    while chunk := await stream.read(CHUNK):
        tail.feed(decoder.decode(chunk))
    tail.feed(decoder.decode(b"", final=True))


def _directory() -> Path:
    instance = os.environ.get("AGENT_CORE_INSTANCE")
    if not instance:
        return Path.cwd()
    if not Path(instance).is_dir():
        raise ValueError(f"AGENT_CORE_INSTANCE is not a directory: {instance}")
    return Path(instance)


def _user_shell() -> str:
    shell = os.environ.get("SHELL")
    return shell if shell and os.access(shell, os.X_OK) else "/bin/sh"


def _end(process: asyncio.subprocess.Process) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


@mcp.tool()
async def run(command: str, timeout: int = 600) -> Ran:
    """Run a shell command as the user, in the instance directory, and return its exit code and output.

    `stdout` and `stderr` are each the last 20,000 characters; `cut` is how many characters were dropped in all.
    A command still running after `timeout` seconds is ended: its exit is -1 and its stderr says it timed out.
    """
    process = await asyncio.create_subprocess_exec(
        _user_shell(), "-c", command,
        stdin=asyncio.subprocess.DEVNULL,  # the server's own stdin carries the protocol
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=_directory(),
        start_new_session=True,  # the command and its children are one group, ended together
    )
    out, err = _Tail(), _Tail()
    drains = [asyncio.create_task(_drain(process.stdout, out)), asyncio.create_task(_drain(process.stderr, err))]
    finished = asyncio.create_task(process.wait())
    try:
        _, pending = await asyncio.wait([finished, *drains], timeout=timeout)
    except asyncio.CancelledError:  # the client gave up on the call: the command must not outlive it
        _end(process)
        raise
    code = process.returncode
    if pending:
        _end(process)
        await process.wait()
        _, stuck = await asyncio.wait(drains, timeout=CLOSE_WAIT)  # something that left the group may hold a pipe open
        for task in stuck:
            task.cancel()
        code = -1
        err.feed(("\n" if err.text and not err.text.endswith("\n") else "") + f"timed out after {timeout} seconds and was ended\n")
    return {"exit": code, "stdout": out.text, "stderr": err.text, "cut": out.cut + err.cut}


if __name__ == "__main__":
    mcp.run()
