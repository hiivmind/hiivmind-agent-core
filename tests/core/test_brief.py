import dataclasses
import json
from pathlib import Path

import pytest

from agent_core.contracts.values import ToolSpec
from agent_core.core.brief import JOB_VERBS, VERB_SPECS, make_brief
from support import FolderSource, load

GOLDENS = Path(__file__).parent / "goldens"

FUNCTION = ToolSpec("lookup", "Look a key up.", {"type": "object"})
SERVER = ToolSpec("tools__lookup", "Look a key up.", {"type": "object"})


def brief(instance, name="plain", *, values=None, tools=None, inputs=None):
    return make_brief(
        instance, instance.nodes[name], inputs=inputs or {}, session={}, values={} if values is None else values,
        settings=None, resources=FolderSource(instance.root), tools={"tools__lookup": SERVER} if tools is None else tools,
    )


def test_a_jobs_instructions_are_those_of_270b974(instance):                               # CD-4
    assert brief(instance)[0] == (GOLDENS / "plain_instructions.txt").read_text()


def test_a_jobs_verb_schemas_are_those_of_270b974(instance):                               # CD-4
    assert [dataclasses.asdict(t) for t in brief(instance)[1]] == json.loads((GOLDENS / "job_verbs.json").read_text())


def test_the_job_verbs_and_their_specs():
    assert JOB_VERBS == ("exit", "ask", "state_set", "state_get", "load")
    assert set(VERB_SPECS) == {"enter", *JOB_VERBS}
    assert all(spec.name == name and spec.description and spec.schema["type"] == "object" for name, spec in VERB_SPECS.items())


def test_the_brief_offers_the_job_verbs_then_the_nodes_tools(instance, broken):           # NODE-6a
    broken.frontmatter("consult", **{"allowed-tools": "[lookup]"})   # a function tool: declared, keyed and offered as `lookup`
    _, tools, _ = brief(load(broken.root), "consult", tools={"lookup": FUNCTION})
    assert [t.name for t in tools] == [*JOB_VERBS, "lookup"]
    _, tools, _ = brief(instance)
    assert [t.name for t in tools] == list(JOB_VERBS)


def test_a_server_tool_is_declared_keyed_and_offered_under_one_name(instance):
    _, tools, _ = brief(instance, "consult", tools={"tools__lookup": SERVER})
    assert [t.name for t in tools] == [*JOB_VERBS, "tools__lookup"]


def test_the_brief_names_where_each_part_came_from(instance):                             # CTX-6
    text, _, parts = brief(instance)
    assert [p for p, _ in parts] == [
        "engine: rules", "engine: inside a node", "procedure conventions", "policy", "node file: nodes/plain.md",
    ]
    assert all(n > 0 for _, n in parts)


def test_the_node_part_begins_with_its_name_line_and_outcomes(instance):
    text, _, parts = brief(instance)
    node_part = text[text.index("# Procedure of the node that is running:"):]
    outcomes = ", ".join(instance.nodes["plain"].contract.outcomes)
    assert node_part.startswith(f"# Procedure of the node that is running: `plain`\nThe outcomes of this node are: {outcomes}.\n\n# Plain")
    assert parts[-1][1] == len(node_part)


def test_the_brief_is_filled_once(instance, broken):                                       # TPL-4
    values = {"progress": "3 of 8"}
    broken.append("nodes/plain.md", "\nProgress: {{node.progress}}.\n")
    inst = load(broken.root)
    text, _, _ = brief(inst, values=values)
    values["progress"] = "8 of 8"
    assert "Progress: 3 of 8." in text and "8 of 8" not in text


def test_a_declared_tool_no_tool_set_offers_raises(instance):
    with pytest.raises(ValueError, match=r"`consult` declares the tool `tools__lookup`, which no tool source offers"):
        brief(instance, "consult", tools={})
