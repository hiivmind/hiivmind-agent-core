"""A chat model that plays a script, and the `script` provider module that makes it (tests only).

`MODEL=script:<dir>` names a directory of `<node>.json`, in the format of the scripted backend (a step is a list of
`[name, args]` pairs, one response's calls, or a string, the model saying that and making no call), extended with three
step forms only this model reads:

    {"calls": [...], "text": "...", "usage": {"input_tokens": n, "input_token_details": {...}}}
    {"raise": "passes" | "will not pass" | "other"}      raises ScriptRefusal(kind), once
    {"raise": ..., "once": true}                          the same, in the first conversation of the node that reaches it
    {"crash": true}                                       raises SystemExit, once, whatever the process

The model finds the node in the run config's `metadata["agent_core_node"]`, which the backend sets. It finds its place in the script by progress that is
scoped to ONE CONVERSATION: the conversation's key is the invocation config's `thread_id` (`invoke(..., config=...)` or the graph's; when there is one) with the id, or
else the text, of the first message that is not a system message. The place is

    (the answers in the conversation that this model produced for this node's script: they carry
     `response_metadata["script"]`, so a hand-over's earlier answers are not counted)
  + (the `raise` and `crash` steps already played in this conversation)

and the played `raise`/`crash` steps are kept in `<dir>/<node>.<hash of the key>.progress.json`, so a rebuilt model, or
a process that resumes, does not play a crash again and does not play a refusal again. A retry of a model call (the same
conversation, the same place) therefore finds the next step after a `raise`. A FRESH run of an item (RTY-2) is found by
its key: it has a new conversation (a new thread id, or a new first message), so it starts at the first step; a fresh run
that kept the same thread id and the same first message would continue where the earlier one stopped.
"""

import hashlib
from contextvars import ContextVar
import json
from pathlib import Path
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables.config import var_child_runnable_config

from agent_core.contracts.registry import register
from agent_core.contracts.values import Usage

_EXPLICIT: ContextVar = ContextVar("script_model_config", default=None)


class ScriptRefusal(Exception):
    def __init__(self, kind: str):
        super().__init__(f"scripted refusal that {kind}")
        self.kind = kind


class ScriptChatModel(BaseChatModel):
    directory: Path

    @property
    def _llm_type(self) -> str:
        return "script"

    def bind_tools(self, tools, **kwargs: Any):
        return self   # the script says which calls are made; the tools it is offered do not change it

    @staticmethod
    def _config() -> dict:
        return _EXPLICIT.get() or var_child_runnable_config.get() or {}   # inside LangGraph the context variable has it

    def _node(self) -> str:
        node = (self._config().get("metadata") or {}).get("agent_core_node")
        if node is None:
            raise ValueError("the run config has no metadata `agent_core_node` naming the node that is running")
        return node

    def invoke(self, input, config=None, **kwargs):
        token = _EXPLICIT.set(config)   # the config of this call: the base class does not install it in the context variable
        try:
            return super().invoke(input, config, **kwargs)
        finally:
            _EXPLICIT.reset(token)

    async def ainvoke(self, input, config=None, **kwargs):
        token = _EXPLICIT.set(config)
        try:
            return await super().ainvoke(input, config, **kwargs)
        finally:
            _EXPLICIT.reset(token)

    @classmethod
    def _key(cls, messages: list[BaseMessage]) -> str:
        thread = (cls._config().get("configurable") or {}).get("thread_id", "")
        first = next((m for m in messages if not isinstance(m, SystemMessage)), None)
        said = "" if first is None else (first.id or first.text)
        return hashlib.sha1(f"{thread}\0{said}".encode()).hexdigest()[:12]

    def _progress_file(self, node: str, key: str) -> Path:
        return self.directory / f"{node}.{key}.progress.json"

    def _played(self, node: str, key: str) -> int:
        file = self._progress_file(node, key)
        return int(file.read_text()) if file.exists() else 0

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs: Any) -> ChatResult:
        node = self._node()
        key = self._key(messages)
        steps = json.loads((self.directory / f"{node}.json").read_text())
        answered = sum(
            isinstance(message, AIMessage) and message.response_metadata.get("script") == node for message in messages
        )
        played = self._played(node, key)
        position = answered + played
        step = steps[position] if position < len(steps) else ""   # a script that runs out is the model stopping with nothing said
        while isinstance(step, dict) and step.get("once"):   # a refusal a conversation of the node has played before is passed over
            marker = self.directory / f"{node}.{position}.once"
            if not marker.exists():
                marker.write_text("")
                break
            self._progress_file(node, key).write_text(str(played + 1))
            played += 1
            position += 1
            step = steps[position] if position < len(steps) else ""
        if isinstance(step, dict) and "raise" in step:
            self._progress_file(node, key).write_text(str(played + 1))
            raise ScriptRefusal(step["raise"])
        if isinstance(step, dict) and step.get("crash"):
            self._progress_file(node, key).write_text(str(played + 1))
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
            response_metadata={"script": node},
        )
        if usage is not None:
            message.usage_metadata = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, **usage}
        return ChatResult(generations=[ChatGeneration(message=message)])


class ScriptProvider:
    name = "script"
    packages: tuple[str, ...] = ()

    def chat_model(self, model: str, settings) -> BaseChatModel:
        return ScriptChatModel(directory=Path(model))

    def classify(self, error: BaseException, settings) -> Literal["passes", "will not pass", "other"]:
        return error.kind if isinstance(error, ScriptRefusal) else "other"

    def refusal(self, error: BaseException, settings) -> str:
        return f"the provider refused: {error}"

    def middleware(self, settings) -> list:
        return []

    def usage(self, message: AIMessage) -> Usage:
        meta = message.usage_metadata
        if not meta:
            return Usage()
        details = meta.get("input_token_details") or {}
        return Usage(meta.get("input_tokens"), details.get("cache_read"), details.get("cache_creation"))


register("model_provider", "script")(ScriptProvider())   # an instance: `provider_module` returns it, and its methods are bound
