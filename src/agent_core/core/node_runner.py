"""Run one node of a job: the checks before it starts, the brief, the driver, and the result (JOB-4, JOB-13)."""

from collections.abc import Mapping, Sequence
from importlib.resources import files

from agent_core.contracts.backend import NodeDriver
from agent_core.contracts.context import HandoverRequest
from agent_core.contracts.person import Person
from agent_core.contracts.resources import ResourceSource
from agent_core.contracts.tools import ToolSource
from agent_core.contracts.values import Brief, Message, ModelResponse, ToolSpec
from agent_core.core.checks import unknown_inputs, unmet_precondition
from agent_core.core.controller import VERB_SPECS, Controller, NodeRun
from agent_core.core.instance import Instance, Node
from agent_core.core.record import NodeRunNote
from agent_core.core.registry import provider
from agent_core.core.state import HarnessState, Slot, record_value
from agent_core.core.templates import TemplateError, render

JOB_VERBS = ("exit", "ask", "state_set", "state_get", "load")  # what a job's node is offered besides its own tools (R9)
INSIDE_A_NODE = "## Inside a node"


class NodeRunError(RuntimeError):
    """The provider failed during a node run. The message names the run."""


def _asset(name: str) -> str:
    return files("agent_core.assets").joinpath(name).read_text().strip()


def _require_declared_tools(node: Node, tools: Mapping[str, tuple[ToolSource, ToolSpec]]) -> None:
    for name in node.allowed_tools:
        if name not in tools:
            raise ValueError(f"`{node.name}` declares the tool `{name}`, which no tool source offers")


async def _cannot_summarise(system: str, text: str) -> str:
    raise RuntimeError("a job's node run has no summariser in this version")


def make_brief(
    instance: Instance,
    node: Node,
    slot: Slot,
    state: HarnessState,
    *,
    settings: object | None,
    resources: ResourceSource,
    tools: Mapping[str, tuple[ToolSource, ToolSpec]],
    job: bool,
    handover: Sequence[Message] = (),
    opening: str = "Run the node.",
) -> tuple[Brief, list[tuple[str, str]]]:
    """The brief of a node run, and (where it came from, text) for each part of its instructions (CTX-6).

    The procedure is filled here, once; it does not change while the run lasts (TPL-4). Step 1a runs jobs only.
    """
    if not job:
        raise ValueError("only a job's node run is made in this version; sessions arrive with step 2")
    _require_declared_tools(node, tools)
    rules, inside = _asset("ENGINE.md").split(INSIDE_A_NODE, 1)
    procedure = render(
        node.body,
        file=node.file,
        settings=settings,
        inputs=slot.inputs,
        session=state.session,
        values=slot.values,
        resources=resources,
    ).strip()
    parts = [
        ("engine: rules", rules.strip()),
        ("engine: inside a node", f"{INSIDE_A_NODE}{inside}".strip()),
        ("procedure conventions", _asset("PROCEDURES.md")),
        ("policy", instance.policy.strip()),
        (
            f"node file: {node.file}",
            f"# Procedure of the node that is running: `{node.name}`\n"
            f"The outcomes of this node are: {', '.join(node.exits)}.\n\n{procedure}",
        ),
    ]
    specs = (*(VERB_SPECS[name] for name in JOB_VERBS), *(tools[name][1] for name in node.allowed_tools))
    brief = Brief(
        instructions="\n\n".join(text for _, text in parts), tools=specs, handover=tuple(handover), opening=opening
    )
    return brief, parts


def _total(counts: list[int | None]) -> int | None:
    return None if any(c is None for c in counts) else sum(counts)


def _note(label: str, node: str, parts: list[tuple[str, str]], brief: Brief, usage: list[ModelResponse]) -> NodeRunNote:
    return NodeRunNote(
        label=label,
        node=node,
        parts=[(source, len(text)) for source, text in parts],
        tools=[spec.name for spec in brief.tools],
        handover=[m.text for m in brief.handover],
        model_calls=len(usage),
        tokens_sent=_total([u.sent for u in usage]),
        cache_read=_total([u.cache_read for u in usage]),
        cache_written=_total([u.cache_written for u in usage]),
    )


class NodeRunner:
    """Runs the nodes of one instance. It keeps no facts between runs: each run starts from the state it is given, or a
    fresh one (JOB-4)."""

    def __init__(
        self,
        instance: Instance,
        settings: object | None,
        tools: Mapping[str, tuple[ToolSource, ToolSpec]],
        functions: frozenset[str],
        person: Person,
        resources: ResourceSource,
        notes: list[NodeRunNote],
    ):
        self.instance, self.settings, self.tools, self.functions = instance, settings, tools, functions
        self.person, self.resources, self.notes = person, resources, notes

    async def run(
        self, node: str, inputs: dict, *, driver: NodeDriver, label: str, job: bool = True,
        state: HarnessState | None = None,
    ) -> dict:
        found = self.instance.nodes.get(node)
        if found is None:
            raise ValueError(f"no node `{node}`; the nodes are: {', '.join(self.instance.nodes)}")
        if (refusal := unknown_inputs(found, inputs)) is not None:  # NODE-8a: before anything else
            raise ValueError(refusal)
        _require_declared_tools(found, self.tools)  # a misdeclared node fails before any tool is called
        if state is None:
            state = HarnessState(session={})
        slot = state.node = Slot(found.name, dict(inputs), {}, {})

        def fill(text: str) -> str:
            return render(
                text, file=found.file, settings=self.settings, inputs=slot.inputs, session=state.session,
                values=slot.values, resources=self.resources,
            )

        try:
            unmet, writes = await unmet_precondition(
                found, slot.inputs, state.session,
                tools=self.tools, functions=set(self.functions), fill=fill,
            )
            if unmet is not None:  # NODE-13: the driver is never called
                return {"outcome": "failed", "reason": "precondition_unmet", "message": unmet, "outputs": {}}
            for key, value in writes:  # what a met check wrote counts as recorded when the node starts (NODE-11)
                record_value(state, slot, found, key, value)
            strategy = provider("context", "none")()  # a job's node gets its hand-over from the first strategy
            handover = await strategy.build(HandoverRequest(
                transcript=tuple(state.transcript), facts=state.session, node=found.name, inputs=slot.inputs,
                summarise=_cannot_summarise,
            ))
            brief, parts = make_brief(
                self.instance, found, slot, state,
                settings=self.settings, resources=self.resources, tools=self.tools, job=job, handover=handover,
            )
        except TemplateError as e:  # TPL-2b, TPL-6b
            return {"outcome": "failed", "reason": "unknown_placeholder", "detail": str(e), "outputs": {}}

        run = NodeRun(
            node=found, slot=slot, state=state, offered=frozenset(spec.name for spec in brief.tools),
            tools=dict(self.tools), functions=self.functions, person=self.person, resources=self.resources,
            job=job, label=label, record=[], usage=[],
        )
        controller = Controller(run)
        try:
            end = await driver.drive(brief, controller)
        except Exception as e:
            raise NodeRunError(f"{label}: {type(e).__name__}: {e}") from e
        finally:
            self.notes.append(_note(label, found.name, parts, brief, run.usage))
        if run.result is not None:
            return run.result
        if run.fault is not None:  # TOOL-11e: the job's script gets it
            raise run.fault
        return {"outcome": "failed", "reason": "no_exit", "said": end.said, "outputs": {}}
