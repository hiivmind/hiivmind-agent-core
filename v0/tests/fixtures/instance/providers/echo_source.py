"""A tool source of the instance's own: one tool, `say`, that returns its text, named `<key>__say` like a server's.

Closing it leaves a mark in the run's directory, the evidence that the run closed it.
"""

import os
from pathlib import Path

from agent_core.contracts.registry import register
from agent_core.contracts.values import ToolSpec


@register("tool_source", "echo")
class EchoSource:
    def __init__(self, key: str, entry: dict, instance_root: Path):
        self._key = key

    async def tools(self) -> tuple[ToolSpec, ...]:
        schema = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}
        return (ToolSpec(f"{self._key}__say", "Say the text back.", schema),)

    async def call(self, name: str, args: dict, state: dict) -> object:
        return args["text"]

    async def close(self) -> None:
        (Path(os.environ["AGENT_CORE_RUN_DIR"]) / f"{self._key}.closed").touch()
