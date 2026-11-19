"""The MCP client helper: a `ToolSource` for MCP servers, reached with MCP's own Python SDK.

One connection to each server is held for the run. A connection that fails is dropped, and the next call opens another.
"""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

from agent_core.contracts.errors import RunCannotStart, ToolError, ToolServerError
from agent_core.contracts.values import ToolSpec


class _CannotConnect(Exception):
    """A server could not be started or reached; the text names it (TOOL-11c). Made into the error of the caller."""


@dataclass(eq=False)
class _Connection:
    """One connection, opened and closed by `task` alone: the SDK requires the opener to be the closer."""

    closing: asyncio.Event = field(default_factory=asyncio.Event)
    ready: asyncio.Future = field(default_factory=lambda: asyncio.get_running_loop().create_future())
    task: asyncio.Task | None = None
    session: ClientSession | None = None
    tools: tuple[ToolSpec, ...] = ()


class McpServers:
    def __init__(self, declared: Mapping[str, dict], env: Mapping[str, str], root: Path):
        self._declared = declared
        self._env = env
        self._root = root
        self._held: dict[str, _Connection] = {}
        self._opening = {server: asyncio.Lock() for server in declared}

    async def tools(self) -> tuple[ToolSpec, ...]:
        """Connect to each server and return its tools, each named `server__tool`.
        A server that cannot be started or reached is a run that cannot start (TOOL-11c)."""
        found: list[ToolSpec] = []
        for server in self._declared:
            try:
                found += (await self._open(server)).tools
            except _CannotConnect as e:
                raise RunCannotStart(str(e)) from None
        return tuple(found)

    async def call(self, name: str, args: dict, state: dict) -> object:
        server, _, tool = name.partition("__")
        try:
            connection = await self._open(server)  # opens again if the connection was dropped
        except _CannotConnect as e:
            raise ToolServerError(server, tool, e) from None
        try:
            result = await connection.session.call_tool(tool, args)
        except Exception:
            await self._drop(server, connection)
            raise ToolServerError(server, tool, "it stopped answering") from None
        text = "".join(getattr(block, "text", "") for block in result.content)
        if result.isError:  # the server said the call failed
            raise ToolError(text)
        return text

    async def close(self) -> None:
        for server, connection in list(self._held.items()):
            await self._drop(server, connection)

    async def _open(self, server: str) -> _Connection:
        async with self._opening[server]:
            connection = self._held.get(server)
            if connection is None:
                connection = self._held[server] = _Connection()
                connection.task = asyncio.create_task(self._hold(server, connection))
            try:
                await connection.ready
            except BaseException:
                await self._drop(server, connection)
                raise
            return connection

    async def _hold(self, server: str, connection: _Connection) -> None:
        spec = self._declared[server]
        try:
            if "url" in spec:
                opened = streamable_http_client(spec["url"])
            else:
                params = StdioServerParameters(
                    command=spec["command"], args=spec.get("args") or [], env=dict(self._env), cwd=self._root
                )
                opened = stdio_client(params)
            async with opened as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    listed = (await session.list_tools()).tools
                    connection.session = session
                    connection.tools = tuple(
                        ToolSpec(f"{server}__{t.name}", t.description or t.name, t.inputSchema) for t in listed
                    )
                    connection.ready.set_result(None)
                    await connection.closing.wait()
        except BaseException as e:  # noqa: BLE001 -- whatever ended the connection, the caller is told only if it is still waiting
            if not connection.ready.done():
                connection.ready.set_exception(_CannotConnect(self._why(server, e)))

    async def _drop(self, server: str, connection: _Connection) -> None:
        """Close `connection`. It is forgotten only if it is still the one held: a late failure of a connection
        that was already replaced must not close its replacement."""
        if self._held.get(server) is connection:
            del self._held[server]
        connection.closing.set()
        await asyncio.wait([connection.task], timeout=5)
        if connection.ready.done() and not connection.ready.cancelled():
            connection.ready.exception()  # retrieved: the caller that was waiting for it may have gone

    def _why(self, server: str, e: BaseException) -> str:
        return why_not_connected(server, self._declared[server], e)


def why_not_connected(server: str, spec: Mapping, error: BaseException) -> str:
    """What to tell of a server that could not be started or reached (TOOL-11c): the text of the run that cannot start.
    `error` is what ended the attempt, an exception group included. Both ways of reaching a server (this helper and a
    backend's own) say it in these words."""
    if "url" in spec:
        return f'tool server "{server}" could not be reached at {spec["url"]}'
    leaves, queue = [], [error]
    while queue:
        x = queue.pop()
        if hasattr(x, "exceptions"):
            queue.extend(x.exceptions)
        else:
            leaves.append(x)
    if any(isinstance(x, FileNotFoundError) for x in leaves):
        return f'tool server "{server}" could not be started: no such command "{spec["command"]}"'
    return f'tool server "{server}" could not be started: it closed the connection before answering'
