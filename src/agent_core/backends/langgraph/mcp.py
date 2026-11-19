"""Tool servers through `langchain-mcp-adapters`: a `ToolSource` that holds one adapter session per server for a run.

The adapter owns the connections and the sessions: `MultiServerMCPClient.session(server)` opens one, and
`load_mcp_tools(session)` lists its tools and binds each to the session. The MCP SDK under it requires the task that opened
a session to be the one that closes it, so each session is opened, held and closed by a task of its own. A call is the
adapter's tool invoked on the held session: a server's error result comes back as a `ToolMessage` with status `error`
and the server's own text (TOOL-11a).

A session that fails is dropped, and the next call opens another (TOOL-15). The SDK does not answer a request that was
sent into a connection that was closing, and it does not tell a session's user that the connection has gone, so the
source watches for it: a call waits for the SDK's answer or for the session to be lost, whichever comes first (TOOL-11e).
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


class _Pending(dict):
    """The SDK session's table of requests waiting for an answer. The SDK clears it as the last act of its receive loop,
    when the connection has closed, whether or not it managed to tell each waiting request: that is the signal that the
    session is lost, and it is raised here, for the requests that registered while the loop was ending and are dropped by
    that `clear` among them."""

    def __init__(self, lost: asyncio.Event):
        super().__init__()
        self._lost = lost

    def clear(self) -> None:
        self._lost.set()
        super().clear()


@dataclass(eq=False)
class _Session:
    """One held adapter session, opened and closed by `task` alone."""

    closing: asyncio.Event = field(default_factory=asyncio.Event)
    lost: asyncio.Event = field(default_factory=asyncio.Event)   # set when the session can answer no more
    ready: asyncio.Future = field(default_factory=lambda: asyncio.get_running_loop().create_future())
    task: asyncio.Task | None = None
    tools: dict[str, BaseTool] = field(default_factory=dict)


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
        if session.lost.is_set():   # the server went while no call was in flight
            await self._drop(server, session)
            raise ToolServerError(server, tool, "it stopped answering")
        work = asyncio.ensure_future(session.tools[tool].ainvoke({"type": "tool_call", "id": name, "name": tool, "args": args}))
        work.add_done_callback(lambda done: done.cancelled() or done.exception())   # retrieved: nobody may be left to ask
        gone = asyncio.ensure_future(session.lost.wait())
        try:
            await asyncio.wait({work, gone}, return_when=asyncio.FIRST_COMPLETED)
        except BaseException:   # the caller was cancelled: its call goes with it
            work.cancel()
            raise
        finally:
            gone.cancel()
        if not work.done() or work.cancelled() or work.exception() is not None:   # the session is gone, or the server did not answer
            work.cancel()
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
        spec = self._declared[server]
        try:
            async with self._client.session(server) as session:
                session._response_streams = _Pending(held.lost)   # the SDK has none yet: the session is initialized, nothing waits
                loaded = await load_mcp_tools(session, server_name=server)
                held.tools = {tool.name: tool for tool in loaded}
                held.ready.set_result(None)
                await held.closing.wait()
        except BaseException as e:  # noqa: BLE001 -- whatever ended the session, the caller is told only if it is still waiting
            if not held.ready.done():
                held.ready.set_exception(_CannotConnect(why_not_connected(server, spec, e)))
        finally:
            held.lost.set()   # whatever ended the session, the calls waiting on it stop waiting

    async def _drop(self, server: str, session: _Session) -> None:
        """Close `session`; the calls still in flight on it are lost with it (TOOL-11e). It is forgotten only if it is
        still the one held: a late failure of a session that was already replaced must not close its replacement."""
        if self._held.get(server) is session:
            del self._held[server]
        session.lost.set()
        session.closing.set()
        await asyncio.wait([session.task], timeout=5)
        if session.ready.done() and not session.ready.cancelled():
            session.ready.exception()  # retrieved: the caller that was waiting for it may have gone
