"""The brief of a node run: its instructions in parts, and the tools it is offered (CTX-6, NODE-6a)."""

from collections.abc import Mapping
from importlib.resources import files

from agent_core.contracts.resources import ResourceSource
from agent_core.contracts.values import ToolSpec
from agent_core.core.instance import Instance, NodeDef
from agent_core.core.policy import VERBS, Verb, joined, verb_spec
from agent_core.core.templates import render

INSIDE_A_NODE = "## Inside a node"
STAYING_ON_THE_TASK = "## Staying on the task"


def _engine(offered: tuple[Verb, ...]) -> str:
    """ENGINE.md with its verb list and its alone rule written from the verbs offered (CD-3)."""
    verbs = "\n".join(f"- `{v.name}({', '.join(v.args.model_fields)})`: {v.meaning}" for v in offered)
    names = [v.name for v in offered if v.alone]
    alone = (
        f"- {joined(names)} must each be the only call in a response. If you send "
        f"{'either' if len(names) == 2 else 'one of them'} beside another call, none of the calls runs and you must "
        "send them again, separately."
    )
    return _asset("ENGINE.md").replace("<!-- verbs -->", verbs).replace("<!-- alone -->", alone)


def _asset(name: str) -> str:
    return files("agent_core.assets").joinpath(name).read_text().strip()


def _section(text: str, heading: str) -> str:
    """The section of `text` that begins with the line `heading`, up to the next `## ` heading."""
    start = text.index(f"\n{heading}\n") + 1
    end = text.find("\n## ", start + len(heading))
    return text[start:end if end != -1 else len(text)].strip()


def offer(node: NodeDef, tools: Mapping[str, ToolSpec]) -> tuple[ToolSpec, ...]:
    """The tools a node run is offered: the job's verbs, then the node's `allowed-tools` in order (NODE-6a)."""
    return (*(verb_spec(v) for v in VERBS if v.in_job), *(tools[tool] for tool in node.allowed_tools))


def make_brief(
    instance: Instance,
    node: NodeDef,
    *,
    inputs: Mapping,
    session: Mapping,
    values: Mapping,
    settings: object | None,
    resources: ResourceSource,
    tools: Mapping[str, ToolSpec],
    session_mode: bool = False,
) -> tuple[str, tuple[ToolSpec, ...], tuple[tuple[str, int], ...]]:
    """The instructions, the offered tools (the job's verbs, then the node's `allowed-tools` in order), and each
    part's source and length (CTX-6). `session_mode` adds the engine's *Staying on the task* section after *Inside a
    node*, for a node run in a session (DIV-5); a job's brief has none of the session's sections.

    The procedure is filled here, once; it does not change while the run lasts (TPL-4).
    """
    name = node.contract.name
    for tool in node.allowed_tools:
        if tool not in tools:
            raise ValueError(f"`{name}` declares the tool `{tool}`, which no tool source offers")
    engine = _engine(tuple(v for v in VERBS if v.in_job))
    rules = engine.split(INSIDE_A_NODE, 1)[0]
    procedure = render(
        node.body,
        file=node.file,
        settings=settings,
        inputs=inputs,
        session=session,
        values=values,
        resources=resources,
    ).strip()
    parts = (
        ("engine: rules", rules.strip()),
        ("engine: inside a node", _section(engine, INSIDE_A_NODE)),
        *((("engine: staying on the task", _section(engine, STAYING_ON_THE_TASK)),) if session_mode else ()),
        ("procedure conventions", _asset("PROCEDURES.md")),
        ("policy", instance.policy.strip()),
        (
            f"node file: {node.file}",
            f"# Procedure of the node that is running: `{name}`\n"
            f"The outcomes of this node are: {', '.join(node.contract.outcomes)}.\n\n{procedure}",
        ),
    )
    offered = offer(node, tools)
    return "\n\n".join(text for _, text in parts), offered, tuple((source, len(text)) for source, text in parts)
