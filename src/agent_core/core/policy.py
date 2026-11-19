"""Core policy: what one node run may do, written once for every backend (CTL-1 to CTL-7).

`NodePolicy` implements `contracts.policy.Policy`. It holds no state between calls: it reads the `state` it is given and
returns what changed as a `StateUpdate`.
"""

import copy
import json
from collections.abc import Mapping
from typing import TYPE_CHECKING

from jsonschema import Draft202012Validator

from agent_core.contracts.errors import ToolError
from agent_core.contracts.events import EventSink, NodeEnded
from agent_core.contracts.person import Person
from agent_core.contracts.policy import CallResult, Ending, NodeState, Review, StateUpdate
from agent_core.contracts.resources import ResourceSource
from agent_core.contracts.tools import ToolSource
from agent_core.contracts.unit import UnitResult
from agent_core.contracts.values import Message, ModelResponse, ToolCall, ToolSpec
from agent_core.core.checks import StateView, written
from agent_core.core.instance import NodeDef

if TYPE_CHECKING:
    from agent_core.core.functions import FunctionTool

ALONE = {"ask", "enter", "exit"}  # each of these must be the only call in a response (VERB-6)

TOGETHER = (
    "refused: `ask`, `enter` and `exit` must be the only call in a response. "
    "None of the calls in this response ran. Send them again, separately."
)


def _text(value: object) -> str:
    return value if isinstance(value, str) else json.dumps(value)


def _view(state: NodeState) -> StateView:
    """Session facts, then working values, then inputs; a later one hides an earlier of the same name (TOOL-12)."""
    seen = {**state["session"], **state["values"], **state["inputs"]}
    return StateView(copy.deepcopy(seen))


class NodePolicy:
    def __init__(
        self,
        definition: NodeDef,
        *,
        label: str,
        instructions: str,
        tools: tuple[ToolSpec, ...],
        handover: tuple[Message, ...],
        opening: str,
        functions: "Mapping[str, FunctionTool]",
        servers: ToolSource,
        person: Person,
        resources: ResourceSource,
        settings: object | None,
        events: EventSink,
        start: NodeState,
    ):
        self.definition = definition
        self.node = definition.contract.name
        self.label = label
        self.instructions = instructions
        self.tools = tools
        self.handover = handover
        self.opening = opening
        self._offered = frozenset(spec.name for spec in tools)
        self._functions = functions
        self._servers = servers
        self._person = person
        self._resources = resources
        self._settings = settings
        self._events = events
        self._start = start

    def initial(self) -> NodeState:
        return copy.deepcopy(self._start)

    # --- a response ------------------------------------------------------------------------------------------

    def review(self, response: ModelResponse, state: NodeState) -> Review:
        """Refuse before any call of the response runs (VERB-6a, VERB-6b, NODE-6b, CTL-7)."""
        calls = response.calls
        if state["ending"] is not None:
            return Review({c.id: "not run: the node run has ended" for c in calls})
        if len(calls) > 1 and any(c.name in ALONE for c in calls):
            return Review({c.id: TOGETHER for c in calls})
        return Review(
            {
                c.id: f"refused: `{c.name}` is not declared by the node that is running"
                for c in calls
                if c.name not in self._offered
            }
        )

    def stopped(self, said: str, state: NodeState) -> str | None:
        """The model stopped without a call. Nobody is there to reply in a job: the run ends (JOB-12)."""
        return None

    # --- a call ----------------------------------------------------------------------------------------------

    async def call(self, call: ToolCall, state: NodeState) -> CallResult:
        name, args = call.name, call.args
        if name == "exit":
            return self._exit(args.get("outcome"), args.get("outputs") or {}, state)
        if name == "ask":
            return await self._ask(args["question"])
        if name == "state_set":
            key, value = args["key"], args["value"]
            return CallResult(f"recorded {key} = {json.dumps(value)}", update=self._update([(key, value)]))
        if name == "state_get":
            seen = _view(state)
            return CallResult(json.dumps(seen[args["key"]]) if args["key"] in seen else "not set")
        if name == "load":
            try:
                return CallResult(self._resources.read(args["path"]))
            except (OSError, ValueError) as e:
                return CallResult(f"error: {e}", error=True)
        if name in self._functions:
            return self._function(self._functions[name], args, state)
        return await self._server(name, args)

    def _update(self, writes: list[tuple[str, object]]) -> StateUpdate | None:
        """Split writes by where each name belongs: an input, a declared output (also a session fact), or a value."""
        if not writes:
            return None
        contract = self.definition.contract
        inputs, outputs, session, values = {}, {}, {}, {}
        for key, value in writes:
            if key in contract.inputs:
                inputs[key] = value
            elif key in contract.outputs:
                outputs[key] = session[key] = value
            else:
                values[key] = value
        return StateUpdate(inputs=inputs, values=values, outputs=outputs, session=session)

    def _function(self, tool: "FunctionTool", args: dict, state: NodeState) -> CallResult:
        seen = _view(state)
        before = copy.deepcopy(dict(seen))
        given = {"settings": self._settings, "state": seen}
        try:
            value = tool.fn(**args, **{n: given[n] for n in tool.filled})
        except Exception as e:  # nothing it wrote is kept (TOOL-12, TOOL-11a)
            return CallResult(f"error: {tool.name} raised {type(e).__name__}: {e}", error=True)
        text = _text(value)
        writes = written(before, seen)
        if writes:  # a value the function changed reaches the model in the result of the call that changed it
            text += "\n\n(recorded by this call: " + ", ".join(f"{k} = {json.dumps(v)}" for k, v in writes) + ")"
        return CallResult(text, update=self._update(writes))

    async def _server(self, name: str, args: dict) -> CallResult:
        try:
            value = await self._servers.call(name, args, {})  # ToolServerError is the run's, not the model's (TOOL-11e)
        except ToolError as e:  # a server said the call failed: the model gets the server's own message
            return CallResult(f"error: {e}", error=True)
        return CallResult(_text(value))

    async def _ask(self, question: str) -> CallResult:
        answer = await self._person.ask(question, self.label)
        if answer is None:  # nobody is there: the job ends and says what it needed (JOB-6)
            ending = Ending("failed", {}, reason="needs_input", detail={"question": question})
            return CallResult("not answered: nobody is there", error=True, update=StateUpdate(ending=ending))
        return CallResult(answer)

    def _exit(self, outcome: object, outputs: object, state: NodeState) -> CallResult:
        definition = self.definition
        contract = definition.contract
        if outcome not in contract.outcomes:
            return CallResult(
                f"`{outcome}` is not an outcome of `{contract.name}`; its outcomes are: {', '.join(contract.outcomes)}",
                error=True,
            )
        if isinstance(outputs, dict):
            given = {**state["outputs"], **outputs}  # what was recorded while the node ran, then what EXIT carries (JOB-7a)
            done = outcome == "done"
            schema = {
                "type": "object",
                "properties": definition.output_schemas if done else {**definition.output_schemas, "reason": {"type": "string"}},
                "additionalProperties": False,
                "required": list(contract.outputs) if done else [],
            }
            errors = [
                f"{'/'.join(map(str, e.path)) or 'outputs'}: {e.message}"
                for e in Draft202012Validator(schema).iter_errors(given)
            ]
        else:
            given, errors = {}, [f"outputs: {outputs!r} is not of type 'object'"]
        if errors and state["rejections"] >= 1:  # one correction only (JOB-7b)
            ending = Ending("failed", {}, reason="invalid_output", detail={"errors": errors})
            return CallResult(f"the outputs do not match the node's output schema: {errors}.", error=True,
                              update=StateUpdate(ending=ending))
        if errors:
            return CallResult(
                f"the outputs do not match the node's output schema: {errors}. Correct them and EXIT again.",
                error=True,
                update=StateUpdate(rejected=True),
            )
        return CallResult(f"exited with `{outcome}`", update=StateUpdate(ending=Ending(outcome, given)))

    # --- the end of the run ----------------------------------------------------------------------------------

    def finish(self, state: NodeState, said: str) -> UnitResult:
        ending = state["ending"]
        if ending is None:  # the model stopped without an exit (JOB-12)
            result = UnitResult("failed", {}, reason="no_exit", detail={"said": said})
        else:
            result = UnitResult(
                ending["outcome"], ending["outputs"], reason=ending.get("reason"), detail=ending.get("detail") or {}
            )
        self._events.emit(NodeEnded(self.label, self.node, result.exit, result.reason))
        return result
