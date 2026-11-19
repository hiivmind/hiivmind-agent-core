"""Tool servers through `langchain-mcp-adapters`: a `ToolSource` that holds one adapter session per server for a run.

`MultiServerMCPClient.session(server)` is a context manager, and the MCP SDK under it requires the task that opened a
session to be the one that closes it, so each session is opened, held and closed by a task of its own. The tools the
adapter loads over that session are the ones every call goes through (`load_mcp_tools(session)`), so a server call is made
by the adapter on the held session, never on a session of its own. A session that fails is dropped, and the next call
opens another (TOOL-15).
"""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools

from agent_core.contracts.errors import RunCannotStart, ToolError, ToolServerError
from agent_core.contracts.values import ToolSpec
from agent_core.helpers.mcp import why_not_connected


class _CannotConnect(Exception):
    """A server could not be started or reached; the text names it (TOOL-11c). Made into the error of the caller."""


@dataclass(eq=False)
class _Session:
    """One held adapter session, opened and closed by `task` alone."""

    closing: asyncio.Event = field(default_factory=asyncio.Event)
    ready: asyncio.Future = field(default_factory=lambda: asyncio.get_running_loop().create_future())
    task: asyncio.Task | None = None
    tools: dict[str, BaseTool] = field(default_factory=dict)
    calls: set[asyncio.Task] = field(default_factory=set)   # the calls in flight on this session


def _connection(spec: Mapping, env: Mapping[str, str], root: Path) -> dict:
    """The adapter's connection for a declared server: a command run with this environment in the instance's folder, or a URL."""
    if "url" in spec:
        return {"transport": "http", "url": spec["url"]}
    return {"transport": "stdio", "command": spec["command"], "args": list(spec.get("args") or []), "env": dict(env), "cwd": root}


class AdapterServers:
    def __init__(self, declared: Mapping[str, dict], env: Mapping[str, str], root: Path):
        self._declared = declared
        self._client = MultiServerMCPClient({server: _connection(spec, env, root) for server, spec in declared.items()})
        self._held: dict[str, _Session] = {}
        self._opening = {server: asyncio.Lock() for server in declared}

    async def tools(self) -> tuple[ToolSpec, ...]:
        """Open a session to each server and return its tools, each named `server__tool` (TOOL-14).
        A server that cannot be started or reached is a run that cannot start (TOOL-11c)."""
        found: list[ToolSpec] = []
        for server in self._declared:
            try:
                session = await self._open(server)
            except _CannotConnect as e:
                raise RunCannotStart(str(e)) from None
            found += (ToolSpec(f"{server}__{name}", tool.description or name, tool.args_schema) for name, tool in session.tools.items())
        return tuple(found)

    async def call(self, name: str, args: dict, state: dict) -> object:
        server, _, tool = name.partition("__")
        try:
            session = await self._open(server)  # opens again if the session was dropped
        except _CannotConnect as e:
            raise ToolServerError(server, tool, e) from None
        if tool not in session.tools:
            raise ToolError(f"no tool `{name}`")
        # The call is a task of its own so that a session dropped under it can end it (see `_drop`).
        work = asyncio.ensure_future(session.tools[tool].ainvoke({"type": "tool_call", "id": name, "name": tool, "args": args}))
        session.calls.add(work)
        work.add_done_callback(session.calls.discard)
        try:
            await asyncio.wait({work})
        except BaseException:   # the caller was cancelled: its call goes with it
            work.cancel()
            raise
        if work.cancelled() or work.exception() is not None:   # not a result of the server's: the session is gone, or the server did not answer
            await self._drop(server, session)
            raise ToolServerError(server, tool, "it stopped answering") from None
        message = work.result()
        blocks = [message.content] if isinstance(message.content, str) else message.content
        text = "".join(b if isinstance(b, str) else b.get("text", "") for b in blocks)
        if message.status == "error":  # the server said the call failed
            raise ToolError(text)
        return text

    async def close(self) -> None:
        for server, session in list(self._held.items()):
            await self._drop(server, session)

    async def _open(self, server: str) -> _Session:
        async with self._opening[server]:
            session = self._held.get(server)
            if session is None:
                session = self._held[server] = _Session()
                session.task = asyncio.create_task(self._hold(server, session))
            try:
                await session.ready
            except BaseException:
                await self._drop(server, session)
                raise
            return session

    async def _hold(self, server: str, held: _Session) -> None:
        try:
            async with self._client.session(server) as session:
                loaded = await load_mcp_tools(session, server_name=server)
                held.tools = {tool.name: tool for tool in loaded}
                held.ready.set_result(None)
                await held.closing.wait()
        except BaseException as e:  # noqa: BLE001 -- whatever ended the session, the caller is told only if it is still waiting
            if not held.ready.done():
                held.ready.set_exception(_CannotConnect(why_not_connected(server, self._declared[server], e)))

    async def _drop(self, server: str, session: _Session) -> None:
        """Close `session`, and end the calls still in flight on it: a session that is dropped has failed, and a request
        the SDK sent into a connection that had just closed is answered by nothing, ever, so each call in flight must be
        ended here to fail (TOOL-11e). The session is forgotten only if it is still the one held: a late failure of a
        session that was already replaced must not close its replacement."""
        if self._held.get(server) is session:
            del self._held[server]
        for work in list(session.calls):
            work.cancel()
        session.closing.set()
        await asyncio.wait([session.task], timeout=5)
        if session.ready.done() and not session.ready.cancelled():
            session.ready.exception()  # retrieved: the caller that was waiting for it may have gone
