import pytest
from support import SEQUENCES, load

from agent_core.contracts.topology import END, FanOut, FragmentDef, Link, NodeContract, SequenceDef, Step, ToolList
from agent_core.core.instance import InstanceError, NodeDef


def test_loads_the_fixture(instance):
    assert instance.backend == "scripted" and instance.name == "spike-corpus"
    refresh = instance.nodes["refresh"]
    assert isinstance(refresh, NodeDef)
    assert refresh.allowed_tools == ("tools__shell",) and list(refresh.input_docs) == ["sources"]
    assert refresh.contract == NodeContract("refresh", ("sources",), ("sources_updated", "branch"), ("done", "declined", "failed"))
    assert refresh.contract.outcomes == ("done", "declined", "failed", "skipped", "stopped")
    assert refresh.output_schemas["branch"]["type"] == "string"
    assert refresh.context == "none" and refresh.preconditions == ()
    assert refresh.file == "nodes/refresh.md" and "## Steps" in refresh.body
    assert instance.core == 0 and instance.policy.startswith("The corpus instance")
    assert instance.servers["tools"]["command"] == "python"
    assert instance.functions["count_words"] == "functions:count_words"
    assert instance.settings["class"] == "settings.SpikeSettings"
    assert instance.topology.nodes["refresh"] is refresh.contract
    assert instance.topology.sequences == {} and instance.topology.fragments == {}
    assert instance.improvisation == "on"
    assert instance.root.name == "instance"


def test_a_node_with_no_allowed_tools_line_has_none(instance):          # NODE-6a
    assert instance.nodes["plain"].allowed_tools == ()


def test_a_node_file_is_read_from_its_path(instance, sequences):
    assert instance.nodes["plain"].file == "nodes/plain.md"
    assert sequences.nodes["wrap"].file == "nodes/wrap.md"


def test_a_precondition_loads_as_a_check(instance):
    (check,) = instance.nodes["gated"].preconditions
    assert check.tool == "tools__shell" and check.args == {"command": "test -f {{settings.CORPUS_NAME}}.ready"}
    assert check.message.startswith("The corpus") and check.outcome is None
    assert instance.nodes["gated_broken"].preconditions[0].args == {}


def test_a_node_file_without_frontmatter_names_the_file(broken):
    broken("nodes/refresh.md", "# Refresh\n\nno frontmatter\n")
    with pytest.raises(InstanceError, match=r"nodes/refresh\.md"):
        load(broken.root)


def test_a_node_file_whose_frontmatter_is_not_a_mapping_names_the_file(broken):
    broken("nodes/refresh.md", "---\n- done\n- failed\n---\n# Refresh\n")
    with pytest.raises(InstanceError, match=r"nodes/refresh\.md.*mapping"):
        load(broken.root)


def test_a_node_file_with_unreadable_frontmatter_names_the_file(broken):
    broken("nodes/refresh.md", "---\nname: [refresh\n---\n# Refresh\n")
    with pytest.raises(InstanceError, match=r"nodes/refresh\.md"):
        load(broken.root)


def test_bare_on_and_off_in_the_topology_are_read_as_on_and_off(broken):
    assert load(broken.root).improvisation == "on"                      # the fixture writes it quoted
    text = (broken.root / "topology.yaml").read_text().replace('setting: "on"', "setting: off")
    broken("topology.yaml", text)
    assert load(broken.root).improvisation == "off"


def test_a_topology_without_an_improvisation_block_has_none(sequences):
    assert sequences.improvisation is None


def test_a_node_file_that_is_missing_names_the_file(broken):
    (broken.root / "nodes" / "plain.md").unlink()
    with pytest.raises(InstanceError, match=r"nodes/plain\.md"):
        load(broken.root)


def test_a_key_written_twice_is_refused(broken):
    broken.append("instance.yaml", "  count_words: functions:read_ledger\n")
    with pytest.raises(InstanceError, match=r"instance\.yaml.*count_words"):
        load(broken.root)


def test_a_key_written_twice_in_a_node_file_names_the_file(broken):
    path = broken.root / "nodes" / "plain.md"
    path.write_text(path.read_text().replace("inputs: {}", "inputs: {}\ninputs: {}", 1))
    with pytest.raises(InstanceError, match=r"nodes/plain\.md.*inputs"):
        load(broken.root)


def test_schema_violation_names_file_and_field(broken):
    broken.remove_key("instance.yaml", "entry")
    with pytest.raises(InstanceError, match=r"instance\.yaml.*entry"):
        load(broken.root)


def test_a_topology_violation_names_the_file(broken):
    text = (broken.root / "topology.yaml").read_text()
    broken("topology.yaml", text.replace("exits:\n  done: route\n  declined: route\n  failed: route\n", ""))
    with pytest.raises(InstanceError, match=r"topology\.yaml.*exits"):
        load(broken.root)


def test_the_sequences_fixture_loads(sequences):
    refresh = sequences.topology.sequences["refresh"]
    assert isinstance(refresh, SequenceDef) and refresh.start == Step("update-sources")
    assert refresh.description == "Bring the corpus up to date with its sources."
    assert [c.tool for c in refresh.checks] == ["ready", "index_is_v2", "refresh_needed"]
    assert refresh.checks[1].outcome == "v1" and refresh.checks[0].outcome is None
    assert refresh.transitions["check"] == {"v1": Link("migrate"), "current": END}
    assert refresh.transitions["update-sources"]["updated"] == FanOut("scan", "rescan_batches", "batch", "scan_results", 1)
    assert refresh.transitions["scan"]["done"] == Step("index", {"scans": "scan_results"})
    assert refresh.transitions["index"]["done"] == Step("verify")
    enrich = sequences.topology.sequences["enrich"]
    assert enrich.start == FanOut("scan", ToolList("stale_batches"), "batch", "scans", 4)
    assert sequences.topology.sequences["graph"].inputs == {"action": "show"}
    assert sequences.topology.nodes["scan"] is sequences.nodes["scan"].contract
    assert SEQUENCES.name == "sequences"


def test_a_fragment_loads_as_a_fragmentdef(sequences):                  # ORC-3
    t = sequences.topology
    assert isinstance(t.fragments["tail"], FragmentDef)
    assert t.fragments["tail"].exits == ("done", "failed") and t.fragments["tail"].start == Step("wrap")
    assert t.fragments["tail"].transitions["wrap"] == {"done": Step("close"), "failed": END}
    assert "close" in t.nodes


def test_a_transition_names_a_fragment_as_it_names_a_node(sequences):   # ORC-4
    assert sequences.topology.sequences["with-tail"].transitions["first"]["done"] == Step("tail")


def test_a_transition_to_an_unknown_step_does_not_load(broken_sequences):
    text = (broken_sequences.root / "topology.yaml").read_text().replace("first: {done: tail,", "first: {done: nope,")
    broken_sequences("topology.yaml", text)
    with pytest.raises(InstanceError, match=r"topology.yaml: no node or fragment `nope`"):
        load(broken_sequences.root)


def test_a_fragment_may_not_link_or_check(broken_sequences):
    text = (broken_sequences.root / "topology.yaml").read_text().replace("failed: end}\n      close", "failed: {link: refresh}}\n      close")
    broken_sequences("topology.yaml", text)
    with pytest.raises(InstanceError, match=r"topology\.yaml.*fragments\.tail"):
        load(broken_sequences.root)


def _sequence(broken, text):
    broken.append("topology.yaml", "sequences:\n" + text)


def test_a_sequence_needs_a_description(broken):                        # §4.1
    _sequence(broken, "  work:\n    start: plain\n    transitions: {plain: {done: end}}\n")
    with pytest.raises(InstanceError, match=r"topology\.yaml.*description"):
        load(broken.root)


@pytest.mark.parametrize("start", ["end", "{link: other}"])
def test_a_start_cannot_be_end_or_a_link(broken, start):                # §4.1
    _sequence(broken, f"  work:\n    description: d\n    start: {start}\n    transitions: {{plain: {{done: end}}}}\n")
    with pytest.raises(InstanceError, match=r"topology\.yaml"):
        load(broken.root)


def test_a_node_context_outside_the_enum_names_file_and_field(broken):
    broken.frontmatter("plain", context="everything")
    with pytest.raises(InstanceError, match=r"nodes/plain\.md.*context"):
        load(broken.root)


def test_a_node_file_may_not_carry_an_improvisation_line(broken):       # DIV-1 per-node override deferred
    broken.frontmatter("refresh", improvisation="off")
    with pytest.raises(InstanceError, match=r"nodes/refresh\.md.*improvisation"):
        load(broken.root)


@pytest.mark.parametrize("key", ["sources", "providers"])
def test_instance_yaml_has_no_sources_or_providers(broken, key):
    broken.append("instance.yaml", f"{key}: {{}}\n" if key == "sources" else "providers: []\n")
    with pytest.raises(InstanceError, match=rf"instance\.yaml.*{key}"):
        load(broken.root)


def test_a_missing_policy_file_names_the_file(broken):
    (broken.root / "POLICY.md").unlink()
    with pytest.raises(InstanceError, match=r"POLICY\.md"):
        load(broken.root)


def test_a_missing_instance_file_names_the_file(broken):
    (broken.root / "instance.yaml").unlink()
    with pytest.raises(InstanceError, match=r"instance\.yaml"):
        load(broken.root)


def test_a_server_declared_by_url_loads(broken):
    text = (broken.root / "instance.yaml").read_text().replace(
        "  web: {command: python, args: [../servers/flaky_server.py]}", "  web: {url: \"http://127.0.0.1:9/mcp\"}")
    broken("instance.yaml", text)
    assert load(broken.root).servers["web"] == {"url": "http://127.0.0.1:9/mcp"}


@pytest.mark.parametrize("entry", ["{args: [x]}", "{command: python, url: \"http://h/mcp\"}"])
def test_a_server_with_neither_or_both_command_and_url_is_refused(broken, entry):
    text = (broken.root / "instance.yaml").read_text().replace(
        "{command: python, args: [../servers/flaky_server.py]}", entry)
    broken("instance.yaml", text)
    with pytest.raises(InstanceError, match=r"instance\.yaml.*servers\.web"):
        load(broken.root)


def test_a_fragment_may_not_name_a_fragment_as_a_target(broken_sequences):
    text = (broken_sequences.root / "topology.yaml").read_text().replace("wrap: {done: close,", "wrap: {done: tail,")
    broken_sequences("topology.yaml", text)
    with pytest.raises(InstanceError, match=r"topology\.yaml: no node `tail`"):
        load(broken_sequences.root)


@pytest.mark.parametrize("entry, missing", [("{tool: ready}", "message"), ("{message: m}", "tool")])
def test_a_malformed_precondition_names_the_file_and_the_key(broken, entry, missing):
    broken.frontmatter("plain", preconditions=f"[{entry}]")
    with pytest.raises(InstanceError, match=rf"nodes/plain\.md.*preconditions\.0.*'{missing}'"):
        load(broken.root)
