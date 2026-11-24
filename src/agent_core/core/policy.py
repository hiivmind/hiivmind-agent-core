"""Core policy: what one node run may do, written once for every backend (CTL-1 to CTL-7).

`NodePolicy` implements `contracts.policy.Policy`. It holds no state between calls: it reads the `state` it is given and
returns what changed as a `StateUpdate`.
"""

import copy
import json
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import BaseModel, Field, ValidationError, WithJsonSchema

from agent_core.contracts.errors import ToolError
from agent_core.contracts.events import EventSink, NodeEnded
from agent_core.contracts.person import Person, Question
from agent_core.contracts.policy import CallResult, Ending, NodeState, Review, StateUpdate
from agent_core.contracts.resources import ResourceSource
from agent_core.contracts.tools import ToolSource
from agent_core.contracts.unit import UnitResult
from agent_core.contracts.values import DONE, FAILED, HarnessReason, Message, ModelResponse, ToolCall, ToolSpec
from agent_core.core.checks import StateView, written
from agent_core.core.functions import tool_schema
from agent_core.core.instance import NodeDef

if TYPE_CHECKING:
    from agent_core.core.functions import FunctionTool

CORRECTIONS = 1  # JOB-7b: outputs that fail the schema are returned once for correction

_Object = Annotated[dict, WithJsonSchema({"type": "object"})]


def _text(value: object) -> str:
    return value if isinstance(value, str) else json.dumps(value)


def _view(state: NodeState) -> StateView:
    """Session facts, then working values, then inputs; a later one hides an earlier of the same name (TOOL-12)."""
    seen = {**state["session"], **state["values"], **state["inputs"]}
    return StateView(copy.deepcopy(seen))


def joined(names: Iterable[str]) -> str:
    """The names sorted and in backticks: "`ask` and `exit`", or "`ask`, `enter` and `exit`"."""
    quoted = [f"`{n}`" for n in sorted(names)]
    return quoted[0] if len(quoted) == 1 else f"{', '.join(quoted[:-1])} and {quoted[-1]}"


def together(names: Iterable[str]) -> str:
    """The refusal of a response that holds an alone verb beside another call (VERB-6a, VERB-6b)."""
    return (
        f"refused: {joined(names)} must be the only call in a response. "
        "None of the calls in this response ran. Send them again, separately."
    )


class NodePolicy:
    def __init__(
        self,
        definition: NodeDef,
        *,
        number: int,  # the node run's number in the harness: its label is `<node>#<number>`
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
        self.number = number
        self.label = f"{self.node}#{number}"
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
        if len(calls) > 1 and any(c.name in _BY_NAME and _BY_NAME[c.name].alone for c in calls):
            refusal = together(v.name for v in VERBS if v.alone and v.name in self._offered)
            return Review({c.id: refusal for c in calls})
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
        verb = _BY_NAME.get(name)
        if verb is not None and verb.body is not None:
            if verb.checked:
                try:
                    args = verb.args.model_validate(args).model_dump()
                except ValidationError as e:  # the model's to correct, as a wrong outcome is (Q3)
                    why = "; ".join(f"{'.'.join(map(str, err['loc'])) or 'arguments'}: {err['msg']}" for err in e.errors())
                    return CallResult(f"error: `{name}`: {why}", error=True)
            return await verb.body(self, args, state)
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

    # --- the end of the run ----------------------------------------------------------------------------------

    def finish(self, state: NodeState, said: str) -> UnitResult:
        ending = state["ending"]
        if ending is None:  # the model stopped without an exit (JOB-12)
            result = UnitResult(FAILED, {}, reason=HarnessReason.NO_EXIT, detail={"said": said})
        else:
            result = UnitResult(
                ending["outcome"], ending["outputs"], reason=ending.get("reason"), detail=ending.get("detail") or {}
            )
        self._events.emit(NodeEnded(self.label, self.node, result.exit, result.reason))
        return result


# --- the verbs ------------------------------------------------------------------------------------------------


async def _ask(policy: NodePolicy, args: dict, state: NodeState) -> CallResult:
    question = args["question"]
    answer = await policy._person.ask(Question(question, policy.node, policy.number, dict(policy._start["inputs"])))
    if answer is None:  # nobody is there: the job ends and says what it needed (JOB-6)
        ending = Ending(FAILED, {}, reason=HarnessReason.NEEDS_INPUT, detail={"question": question})
        return CallResult("not answered: nobody is there", error=True, update=StateUpdate(ending=ending))
    return CallResult(answer)


async def _state_set(policy: NodePolicy, args: dict, state: NodeState) -> CallResult:
    key, value = args["key"], args["value"]
    return CallResult(f"recorded {key} = {json.dumps(value)}", update=policy._update([(key, value)]))


async def _state_get(policy: NodePolicy, args: dict, state: NodeState) -> CallResult:
    seen = _view(state)
    return CallResult(json.dumps(seen[args["key"]]) if args["key"] in seen else "not set")


async def _load(policy: NodePolicy, args: dict, state: NodeState) -> CallResult:
    try:
        return CallResult(policy._resources.read(args["path"]))
    except (OSError, ValueError) as e:
        return CallResult(f"error: {e}", error=True)


async def _exit(policy: NodePolicy, args: dict, state: NodeState) -> CallResult:
    outcome, outputs = args.get("outcome"), args.get("outputs") or {}
    definition = policy.definition
    contract = definition.contract
    if outcome not in contract.outcomes:
        return CallResult(
            f"`{outcome}` is not an outcome of `{contract.name}`; its outcomes are: {', '.join(contract.outcomes)}",
            error=True,
        )
    if isinstance(outputs, dict):
        given = {**state["outputs"], **outputs}  # what was recorded while the node ran, then what EXIT carries (JOB-7a)
        check = definition.outputs_on_done if outcome == DONE else definition.outputs_otherwise
        errors = [f"{'/'.join(map(str, e.path)) or 'outputs'}: {e.message}" for e in check.iter_errors(given)]
    else:
        given, errors = {}, [f"outputs: {outputs!r} is not of type 'object'"]
    if errors and state["rejections"] >= CORRECTIONS:
        ending = Ending(FAILED, {}, reason=HarnessReason.INVALID_OUTPUT, detail={"errors": errors})
        return CallResult(f"the outputs do not match the node's output schema: {errors}.", error=True,
                          update=StateUpdate(ending=ending))
    if errors:
        return CallResult(
            f"the outputs do not match the node's output schema: {errors}. Correct them and EXIT again.",
            error=True,
            update=StateUpdate(rejected=True),
        )
    return CallResult(f"exited with `{outcome}`", update=StateUpdate(ending=Ending(outcome, given)))


class EnterArgs(BaseModel):
    node: str
    inputs: _Object = Field(default_factory=dict)


class ExitArgs(BaseModel):
    outcome: str
    outputs: _Object = Field(default_factory=dict)


class AskArgs(BaseModel):
    question: str


class StateSetArgs(BaseModel):
    key: str
    value: Any


class StateGetArgs(BaseModel):
    key: str


class LoadArgs(BaseModel):
    path: str


@dataclass(frozen=True)
class Verb:
    """A verb of the harness, declared once: its tool spec, its line in the engine document and its body (CD-1)."""

    name: str
    args: type[BaseModel]
    description: str  # the tool's description
    meaning: str  # its line in the engine document
    alone: bool  # must be the only call in a response (VERB-6)
    in_job: bool  # offered to a job's node
    checked: bool  # its arguments are validated before the body runs; `exit` checks its own (CD-7)
    body: Callable[[NodePolicy, dict, NodeState], Awaitable[CallResult]] | None  # None: comes with sessions


VERBS: tuple[Verb, ...] = (
    Verb("enter", EnterArgs, "Enter another node of this instance, with the inputs it declares.",
         "enter another node of this instance, with the inputs it declares.",
         alone=True, in_job=False, checked=True, body=None),
    Verb("exit", ExitArgs, "End the node that is running with one of its outcomes and the outputs it declares.",
         "finish the node that is running, with one of its outcomes and the outputs it declares.",
         alone=True, in_job=True, checked=False, body=_exit),
    Verb("ask", AskArgs, "Ask the person a question and wait for the answer.",
         "ask the person and wait. The tool result is the person's reply. "
         "If nobody is there to answer, the run ends and says what it needed.",
         alone=True, in_job=True, checked=True, body=_ask),
    Verb("state_set", StateSetArgs, "Record a value under a name. Whatever is recorded stays for the rest of the node run.",
         "record a fact under a name.",
         alone=False, in_job=True, checked=True, body=_state_set),
    Verb("state_get", StateGetArgs, "Read a recorded value by name.",
         "read a recorded fact. The result is the value, or `not set`.",
         alone=False, in_job=True, checked=True, body=_state_get),
    Verb("load", LoadArgs, "Read a file of the instance and return its text.",
         "read a file of the instance and get its text.",
         alone=False, in_job=True, checked=True, body=_load),
)
_BY_NAME = {v.name: v for v in VERBS}


def verb_spec(verb: Verb) -> ToolSpec:
    return ToolSpec(verb.name, verb.description, tool_schema(verb.args))
