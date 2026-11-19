"""A chat model that plays a script, and the `script` provider module that makes it (tests only).

`MODEL=script:<dir>` names a directory of `<node>.json`, in the format of the scripted backend (a step is a list of
`[name, args]` pairs, one response's calls, or a string, the model saying that and making no call), extended with three
step forms only this model reads:

    {"calls": [...], "text": "...", "usage": {"input_tokens": n, "input_token_details": {...}}}
    {"raise": "passes" | "will not pass" | "other"}      raises ScriptRefusal(kind), once
    {"crash": true}                                       raises SystemExit, once, whatever the process

The model finds the node by the line of the brief that names it, and the step by what the conversation holds: one step
for each answer already in it, and one for each `raise` or `crash` already played. A `crash` is remembered in a file of
the directory, so that the process that resumes does not crash at the same step.
"""

import json
import re
from pathlib import Path
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr

from agent_core.contracts.registry import register
from agent_core.contracts.values import Usage

PROCEDURE = re.compile(r"^# Procedure of the node that is running: `([^`]+)`", re.MULTILINE)


class ScriptRefusal(Exception):
    def __init__(self, kind: str):
        super().__init__(f"scripted refusal that {kind}")
        self.kind = kind


class ScriptChatModel(BaseChatModel):
    directory: Path
    _raised: dict[str, int] = PrivateAttr(default_factory=dict)   # node -> the `raise` steps played by this model

    @property
    def _llm_type(self) -> str:
        return "script"

    def bind_tools(self, tools, **kwargs: Any):
        return self   # the script says which calls are made; the tools it is offered do not change it

    def _node(self, messages: list[BaseMessage]) -> str:
        for message in messages:
            if isinstance(message, SystemMessage):
                found = PROCEDURE.search(message.text)
                if found:
                    return found.group(1)
        raise ValueError("no message of the conversation names the node that is running")

    def _crashes(self, node: str) -> int:
        file = self.directory / f"{node}.crashes"
        return int(file.read_text()) if file.exists() else 0

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs: Any) -> ChatResult:
        node = self._node(messages)
        steps = json.loads((self.directory / f"{node}.json").read_text())
        answered = sum(isinstance(message, AIMessage) for message in messages)
        position = answered + self._raised.get(node, 0) + self._crashes(node)
        if position >= len(steps):
            raise RuntimeError(f"the script of node {node} has {len(steps)} steps and the model was asked for step {position + 1}")
        step = steps[position]
        if isinstance(step, dict) and "raise" in step:
            self._raised[node] = self._raised.get(node, 0) + 1
            raise ScriptRefusal(step["raise"])
        if isinstance(step, dict) and step.get("crash"):
            (self.directory / f"{node}.crashes").write_text(str(self._crashes(node) + 1))
            raise SystemExit(1)
        text, calls, usage = "", [], None
        if isinstance(step, str):
            text = step
        elif isinstance(step, dict):
            text, calls, usage = step.get("text", ""), step.get("calls", []), step.get("usage")
        else:
            calls = step
        message = AIMessage(
            content=text,
            tool_calls=[
                {"name": name, "args": args, "id": f"{node}-{position + 1}-{index}", "type": "tool_call"}
                for index, (name, args) in enumerate(calls)
            ],
        )
        if usage is not None:
            message.usage_metadata = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, **usage}
        return ChatResult(generations=[ChatGeneration(message=message)])


@register("model_provider", "script")
class ScriptProvider:
    name = "script"
    packages: tuple[str, ...] = ()

    def chat_model(self, model: str, settings) -> BaseChatModel:
        return ScriptChatModel(directory=Path(model))

    def classify(self, error: BaseException) -> Literal["passes", "will not pass", "other"]:
        return error.kind if isinstance(error, ScriptRefusal) else "other"

    def refusal(self, error: BaseException) -> str:
        return f"the provider refused: {error}"

    def cache_middleware(self) -> list:
        return []

    def usage(self, message: AIMessage) -> Usage:
        meta = message.usage_metadata
        if not meta:
            return Usage()
        details = meta.get("input_token_details") or {}
        return Usage(meta.get("input_tokens"), details.get("cache_read"), details.get("cache_creation"))
