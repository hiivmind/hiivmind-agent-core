"""The declared-tool set of a run: function tools and the tools of the tool servers, each named once (TOOL-16)."""

from collections.abc import Mapping

from agent_core.contracts.errors import RunCannotStart
from agent_core.contracts.tools import ToolSource
from agent_core.contracts.unit import DeclaredTools
from agent_core.contracts.values import ToolSpec

from .functions import FunctionTool


async def resolve(
    functions: Mapping[str, FunctionTool], servers: ToolSource, server_names: Mapping[str, str]
) -> DeclaredTools:
    """List the servers' tools now, so a server that cannot start stops the run before it begins (TOOL-11c).

    `server_names` maps a server's name to what a refusal calls it (the instance's `servers:` keys); a server tool is
    named `server__tool`. When the run cannot start, `servers` is closed; otherwise the caller closes it."""
    specs: dict[str, ToolSpec] = {name: tool.spec for name, tool in functions.items()}
    try:
        listed = await servers.tools()
    except RunCannotStart:  # the source says which server and why
        await servers.close()
        raise
    for spec in listed:
        if spec.name in specs:
            server = server_names.get(spec.name.partition("__")[0], spec.name.partition("__")[0])
            where = functions[spec.name].where or spec.name
            await servers.close()
            raise RunCannotStart(
                f'instance.yaml: two tools are named "{spec.name}": function {where} and server "{server}"'
            )
        specs[spec.name] = spec
    return DeclaredTools(specs, frozenset(functions), servers)
