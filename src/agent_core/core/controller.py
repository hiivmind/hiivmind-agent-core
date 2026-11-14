"""The controller: answers each call of one node run, and holds the rules about what a call may do.

A backend drives the model; every call the model makes comes here (CTL-1). The controller owns the node's state,
its tools and its person: the backend never touches them.
"""

import copy
import json
from dataclasses import dataclass

from jsonschema import Draft202012Validator

from agent_core.contracts.errors import ToolError, ToolServerError
from agent_core.contracts.person import Person
from agent_core.contracts.resources import ResourceSource
from agent_core.contracts.tools import ToolSource
from agent_core.contracts.values import EndRun, Message, ModelResponse, Outcome, Result, ToolCall, ToolSpec
from agent_core.core.instance import Node
from agent_core.core.state import HarnessState, Slot, record_value, view, written

VERB_SPECS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in (
        ToolSpec(
            "enter",
            "Enter another node of this instance, with the inputs it declares.",
            {
                "type": "object",
                "properties": {"node": {"type": "string"}, "inputs": {"type": "object"}},
                "required": ["node"],
            },
        ),
        ToolSpec(
            "exit",
            "End the node that is running with one of its outcomes and the outputs it declares.",
            {
                "type": "object",
                "properties": {"outcome": {"type": "string"}, "outputs": {"type": "object"}},
                "required": ["outcome"],
            },
        ),
        ToolSpec(
            "ask",
            "Ask the person a question and wait for the answer.",
            {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]},
        ),
        ToolSpec(
            "state_set",
            "Record a value under a name. Whatever is recorded stays for the rest of the node run.",
            {"type": "object", "properties": {"key": {"type": "string"}, "value": {}}, "required": ["key", "value"]},
        ),
        ToolSpec(
            "state_get",
            "Read a recorded value by name.",
            {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]},
        ),
        ToolSpec(
            "load",
            "Read a file of the instance and return its text.",
            {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        ),
    )
}
VERBS = set(VERB_SPECS)
ALONE = {"ask", "enter", "exit"}  # each of these must be the only call in its response (VERB-6)

TOGETHER = (
    "refused: `ask`, `enter` and `exit` must be the only call in a response. "
    "None of the calls in this response ran. Send them again, separately."
)


@dataclass
class NodeRun:
    """What one controller works on."""

    node: Node
    slot: Slot
    state: HarnessState
    offered: frozenset[str]
    tools: dict[str, tuple[ToolSource, ToolSpec]]
    functions: frozenset[str]
    person: Person
    resources: ResourceSource
    job: bool
    label: str
    record: list[Message]
    usage: list[ModelResponse]
    result: dict | None = None
    fault: Exception | None = None


def _text(value: object) -> str:
    return value if isinstance(value, str) else json.dumps(value)


class Controller:
    def __init__(self, run: NodeRun):
        self.run = run
        self.ended = False
        self._batch: tuple[ToolCall, ...] = ()
        self._left = 0
        self._staged: dict[str, list[tuple[str, object]]] = {}

    async def responded(self, response: ModelResponse) -> None:
        """A response is reported before any of its calls is handled; they all see the state as it stands now (CTL-5)."""
        self.run.usage.append(response)
        self._batch, self._left, self._staged = response.calls, len(response.calls), {}

    async def stopped(self, said: str) -> str | None:
        """The model stopped without a call. Nobody is there to reply in a job: the run ends (JOB-12)."""
        return None

    async def handle(self, call: ToolCall) -> Outcome:
        if self.ended:
            return self._record(call, Result("not run: the node run has ended", error=True))
        outcome, writes = await self._answer(call)
        self._staged[call.id] = writes
        self._left -= 1
        if self._left <= 0:  # the last call of the response is handled: what they wrote is applied, in the response's order
            run = self.run
            for each in self._batch:
                for key, value in self._staged.get(each.id, []):
                    record_value(run.state, run.slot, run.node, key, value)
        if isinstance(outcome, EndRun):
            self.ended = True
            return outcome
        return self._record(call, outcome)

    def _record(self, call: ToolCall, outcome: Result) -> Result:
        self.run.record.append(
            Message("call", call_id=call.id, name=call.name, args=call.args, result=outcome.text)
        )
        return outcome

    async def _answer(self, call: ToolCall) -> tuple[Outcome, list[tuple[str, object]]]:
        run, name, args = self.run, call.name, call.args
        if len(self._batch) > 1 and any(c.name in ALONE for c in self._batch):
            return Result(TOGETHER, error=True), []
        if name not in run.offered:
            return Result(f"refused: `{name}` is not declared by the node that is running", error=True), []
        if name == "exit":
            return self._exit(args.get("outcome"), args.get("outputs") or {}), []
        if name == "ask":
            return await self._ask(args["question"]), []
        if name == "state_set":
            return Result(f"recorded {args['key']} = {json.dumps(args['value'])}"), [(args["key"], args["value"])]
        if name == "state_get":
            seen = view(run.state, run.slot)
            return Result(json.dumps(seen[args["key"]]) if args["key"] in seen else "not set"), []
        if name == "load":
            try:
                return Result(run.resources.read(args["path"])), []
            except (OSError, ValueError) as e:
                return Result(f"error: {e}", error=True), []
        return await self._tool(call)

    async def _tool(self, call: ToolCall) -> tuple[Outcome, list[tuple[str, object]]]:
        run, name = self.run, call.name
        source = run.tools[name][0]
        function = name in run.functions
        seen = view(run.state, run.slot) if function else {}
        before = copy.deepcopy(dict(seen))
        try:
            value = await source.call(name, call.args, seen)
        except ToolServerError as e:  # the tool cannot be reached: the job's script gets it (TOOL-11e)
            run.fault = e
            return EndRun(), []
        except ToolError as e:  # a server said the call failed: the model gets the server's own message
            return Result(f"error: {e}", error=True), []
        except Exception as e:
            if not function:
                raise
            return Result(f"error: {name} raised {type(e).__name__}: {e}", error=True), []  # nothing it wrote is kept
        text = _text(value)
        writes = written(run.node, before, seen) if function else []
        if writes:  # a value the function changed reaches the model in the result of the call that changed it
            text += "\n\n(recorded by this call: " + ", ".join(f"{k} = {json.dumps(v)}" for k, v in writes) + ")"
        return Result(text), writes

    async def _ask(self, question: str) -> Outcome:
        run = self.run
        answer = await run.person.ask(question, run.label)
        if answer is None:  # nobody is there: the job ends and says what it needed (JOB-6)
            run.result = {"outcome": "failed", "reason": "needs_input", "question": question, "outputs": {}}
            return EndRun()
        return Result(answer)

    def _exit(self, outcome: object, outputs: object) -> Outcome:
        run, node, slot = self.run, self.run.node, self.run.slot
        if outcome not in node.exits:
            return Result(
                f"`{outcome}` is not an outcome of `{node.name}`; its outcomes are: {', '.join(node.exits)}", error=True
            )
        if isinstance(outputs, dict):
            given = {**slot.outputs, **outputs}  # what was recorded while the node ran, then what EXIT carries (JOB-7a)
            properties = node.outputs if outcome == "done" else {**node.outputs, "reason": {"type": "string"}}
            schema = {
                "type": "object",
                "properties": properties,
                "additionalProperties": False,
                "required": list(node.outputs) if outcome == "done" else [],
            }
            errors = [
                f"{'/'.join(map(str, e.path)) or 'outputs'}: {e.message}"
                for e in Draft202012Validator(schema).iter_errors(given)
            ]
        else:
            given, errors = {}, [f"outputs: {outputs!r} is not of type 'object'"]
        if errors and slot.rejections >= 1:  # one correction only (JOB-7b)
            run.result = {"outcome": "failed", "reason": "invalid_output", "errors": errors, "outputs": {}}
            return EndRun()
        if errors:
            slot.rejections += 1
            return Result(
                f"the outputs do not match the node's output schema: {errors}. Correct them and EXIT again.", error=True
            )
        run.result = {"outcome": outcome, "outputs": given}
        return EndRun()
