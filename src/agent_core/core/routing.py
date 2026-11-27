"""The routing run of a session (SCOPE-6, ORC-7): a unit whose one tool is `enter`, built and run by the core.

Its response rules are a node run's (`review_calls`, P22). `enter` names a node or a sequence, the sequence first (SEQ-12);
a node's inputs are checked (NODE-8a) and its declared checks made with the session facts (NODE-13), and a refusal is the
call's result. When they pass, the run ends `entered`, and the session starts what it named with what the checks wrote.
"""

import copy
from collections.abc import Mapping

from pydantic import ValidationError

from agent_core.contracts.events import EventSink, NodeEnded
from agent_core.contracts.person import Person
from agent_core.contracts.policy import CallResult, Ending, NodeState, Review, StateUpdate
from agent_core.contracts.topology import Topology
from agent_core.contracts.unit import UnitResult
from agent_core.contracts.values import FAILED, HarnessReason, Message, ModelResponse, ToolCall, ToolSpec
from agent_core.core.checks import CheckError, unknown_inputs
from agent_core.core.policy import EnterArgs, argument_errors, review_calls
from agent_core.core.templates import TemplateError

ROUTING = "@routing"
ENTERED = "entered"


def unknown_name(topology: Topology, name: str) -> str:
    """The refusal of a name that is neither a node nor a sequence (E4, GW-4c)."""
    return (
        f"no node or sequence `{name}`; the nodes are: {', '.join(topology.nodes) or 'none'}; "
        f"the sequences are: {', '.join(topology.sequences) or 'none'}"
    )


class RoutingPolicy:
    """`check(node, inputs, facts)` makes a node's declared checks, as `_Run.check_node` does."""

    node = ROUTING

    def __init__(
        self,
        *,
        label: str,
        topology: Topology,
        instructions: str,
        tools: tuple[ToolSpec, ...],
        handover: tuple[Message, ...],
        opening: str,
        facts: Mapping,
        check,
        person: Person,
        events: EventSink,
    ):
        self.label, self.instructions, self.tools, self.handover, self.opening = label, instructions, tools, handover, opening
        self._topology, self._facts, self._check, self._person, self._events = topology, dict(facts), check, person, events
        self._offered = frozenset(spec.name for spec in tools)

    def initial(self) -> NodeState:
        return NodeState(inputs={}, values={}, outputs={}, session=copy.deepcopy(self._facts), rejections=0, ending=None)

    def review(self, response: ModelResponse, state: NodeState) -> Review:
        return review_calls(response.calls, self._offered, state["ending"] is not None)

    async def responded(self, response: ModelResponse, state: NodeState) -> str | None:
        """As a session node's: the text is told, and a stop without a call is answered by the person (KIT-10)."""
        if response.text:
            await self._person.tell(response.text)
        if response.calls:
            return None
        return await self._person.hear()

    async def call(self, call: ToolCall, state: NodeState) -> CallResult:
        try:
            args = EnterArgs.model_validate(call.args).model_dump()
        except ValidationError as e:
            return CallResult(argument_errors(call.name, e), error=True)
        name, inputs = args["node"], args["inputs"]
        if name in self._topology.sequences:   # SEQ-12: the sequence before the node of the same name
            return self._entered("sequence", name, inputs, {})
        if name not in self._topology.nodes:
            return CallResult(unknown_name(self._topology, name), error=True)
        if (refusal := unknown_inputs(self._topology.nodes[name], inputs)) is not None:   # NODE-8a
            return CallResult(refusal, error=True)
        try:
            unmet, writes = await self._check(name, inputs, state["session"])
        except (TemplateError, CheckError) as e:   # a check that cannot be run is the model's to read (NODE-12)
            return CallResult(f"error: {e}", error=True)
        if unmet is not None:   # NODE-13: the check's message, and the run goes on
            return CallResult(unmet["message"], error=True)
        return self._entered("node", name, inputs, writes)

    @staticmethod
    def _entered(kind: str, name: str, inputs: dict, checked: dict) -> CallResult:
        ending = Ending(ENTERED, {"kind": kind, "name": name, "inputs": dict(inputs), "checked": dict(checked)})
        return CallResult(f"entered the {kind} `{name}`", update=StateUpdate(ending=ending))

    async def finish(self, state: NodeState, said: str) -> UnitResult:
        ending = state["ending"]
        if ending is None:
            result = UnitResult(FAILED, {}, reason=HarnessReason.NO_EXIT, detail={"said": said})
        else:
            result = UnitResult(ending["outcome"], ending["outputs"])
        self._events.emit(NodeEnded(self.label, ROUTING, result.exit, result.reason))
        return result
