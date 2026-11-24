"""The brief of a node run: its instructions in parts, and the tools it is offered (CTX-6, NODE-6a)."""

from collections.abc import Mapping
from importlib.resources import files

from agent_core.contracts.resources import ResourceSource
from agent_core.contracts.values import ToolSpec
from agent_core.core.instance import Instance, NodeDef
from agent_core.core.policy import VERBS, Verb, joined, verb_spec
from agent_core.core.templates import render

INSIDE_A_NODE = "## Inside a node"


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
) -> tuple[str, tuple[ToolSpec, ...], tuple[tuple[str, int], ...]]:
    """The instructions, the offered tools (the job's verbs, then the node's `allowed-tools` in order), and each
    part's source and length (CTX-6).

    The procedure is filled here, once; it does not change while the run lasts (TPL-4).
    """
    name = node.contract.name
    for tool in node.allowed_tools:
        if tool not in tools:
            raise ValueError(f"`{name}` declares the tool `{tool}`, which no tool source offers")
    job_verbs = tuple(v for v in VERBS if v.in_job)
    rules, inside = _engine(job_verbs).split(INSIDE_A_NODE, 1)
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
        ("engine: inside a node", f"{INSIDE_A_NODE}{inside}".strip()),
        ("procedure conventions", _asset("PROCEDURES.md")),
        ("policy", instance.policy.strip()),
        (
            f"node file: {node.file}",
            f"# Procedure of the node that is running: `{name}`\n"
            f"The outcomes of this node are: {', '.join(node.contract.outcomes)}.\n\n{procedure}",
        ),
    )
    offered = (*(verb_spec(v) for v in job_verbs), *(tools[tool] for tool in node.allowed_tools))
    return "\n\n".join(text for _, text in parts), offered, tuple((source, len(text)) for source, text in parts)
