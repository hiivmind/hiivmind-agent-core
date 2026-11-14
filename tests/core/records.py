"""What the fixture servers and functions recorded in a run's directory: the evidence of which tools really ran."""

import json
from pathlib import Path


def _lines(file: Path) -> list[dict]:
    return [json.loads(line) for line in file.read_text().splitlines()] if file.exists() else []


def tool_calls(run_dir: Path, tool: str | None = None) -> list[dict]:
    """Calls the fixture MCP servers received, in order; `tool` keeps one tool's."""
    return [c for c in _lines(run_dir / "tool_calls.jsonl") if tool is None or c["tool"] == tool]


def shell_commands(run_dir: Path) -> list[str]:
    return [c["args"]["command"] for c in tool_calls(run_dir, "shell")]


def function_calls(run_dir: Path, tool: str) -> list[dict]:
    """Calls of one fixture function tool, in order."""
    return [c for c in _lines(run_dir / "function_calls.jsonl") if c["tool"] == tool]
