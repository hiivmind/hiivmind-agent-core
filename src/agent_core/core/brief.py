"""The brief of a node run: its instructions in parts, and the tools it is offered (CTX-6, NODE-6a)."""

from collections.abc import Mapping
from importlib.resources import files

from agent_core.contracts.resources import ResourceSource
from agent_core.contracts.values import ToolSpec
from agent_core.core.instance import Instance, NodeDef
from agent_core.core.templates import render

JOB_VERBS = ("exit", "ask", "state_set", "state_get", "load")  # what a job's node is offered besides its own tools
INSIDE_A_NODE = "## Inside a node"

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
    rules, inside = _asset("ENGINE.md").split(INSIDE_A_NODE, 1)
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
    offered = (*(VERB_SPECS[verb] for verb in JOB_VERBS), *(tools[tool] for tool in node.allowed_tools))
    return "\n\n".join(text for _, text in parts), offered, tuple((source, len(text)) for source, text in parts)
