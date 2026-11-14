# agent-tools

Tool servers for agent-core instances, in a distribution of their own: the core ships no tools (CORE-4a, CORE-4b).
This package does not import `agent_core`; an instance reaches a server over MCP's stdio, like any other.

## The shell server

An instance declares it:

```yaml
servers:
  shell: {command: python, args: [-m, agent_tools.shell_server]}
```

It has one tool, named `shell__run` in the instance:

```
run(command: str, timeout: int = 600) -> {"exit": int, "stdout": str, "stderr": str, "cut": int}
```

- The command runs through the user's shell (`$SHELL`, else `/bin/sh`), as the user, with the user's environment, in
  the directory named by `AGENT_CORE_INSTANCE` when it is set and in the current directory otherwise. Nothing limits
  the commands, the paths or the network (TOOL-8). Standard input is empty.
- `stdout` and `stderr` are each the last 20,000 characters. `cut` is how many characters were dropped in all, so a
  result with `cut` above 0 is a result the model has seen only the tail of.
- A command still running after `timeout` seconds is ended, with its children. Its `exit` is `-1`, its `stderr` ends
  with `timed out after <n> seconds and was ended`, and its output up to then is kept.

## File tools

The file tools are not written here (TOOL-7). An instance declares the reference filesystem server for them:

```yaml
servers:
  files: {command: npx, args: [-y, "@modelcontextprotocol/server-filesystem", "/"]}
```

The server names its tools `read_text_file`, `write_file`, `edit_file`, `search_files` and `list_directory` (among
others), so a node declares them as `files__read_text_file`, `files__write_file`, `files__edit_file`,
`files__search_files` and `files__list_directory`. The last argument is the directory the server may reach; `/` is no
restriction.

## Tests

`uv run pytest packages/agent-tools -q`. Each test reaches the server through agent-core's `McpServerSource`, as an
instance does. The test of the file server needs `npx` and is skipped where it is absent.
