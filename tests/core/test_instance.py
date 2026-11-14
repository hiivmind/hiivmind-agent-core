import pytest

from agent_core.contracts.registry import REGISTERED
from agent_core.core.instance import InstanceError


def test_loads_the_fixture(instance):
    assert instance.backend == "scripted" and instance.name == "spike-corpus"
    refresh = instance.nodes["refresh"]
    assert refresh.allowed_tools == ("tools__shell",) and list(refresh.inputs) == ["sources"]
    assert refresh.exits == ("done", "declined", "failed") and refresh.context == "none"
    assert refresh.file == "skills/refresh/SKILL.md" and "## Steps" in refresh.body
    assert instance.core == 0 and instance.policy.startswith("The corpus instance")
    assert instance.servers["tools"]["command"] == "python"
    assert instance.functions["count_words"] == "functions:count_words"
    assert instance.settings["class"] == "settings.SpikeSettings"
    assert instance.topology["exits"] == {"done": "route", "declined": "route", "failed": "route"}
    assert instance.providers == () and instance.sources == {}
    assert instance.root.name == "instance"


def test_a_node_with_no_allowed_tools_line_has_none(instance):          # NODE-6a
    assert instance.nodes["plain"].allowed_tools == ()


def test_a_node_file_without_frontmatter_names_the_file(broken, load):   # Review Focus 2
    broken("skills/refresh/SKILL.md", "# Refresh\n\nno frontmatter\n")
    with pytest.raises(InstanceError, match=r"skills/refresh/SKILL\.md"):
        load()


def test_a_node_file_whose_frontmatter_is_not_a_mapping_names_the_file(broken, load):   # R10
    broken("skills/refresh/SKILL.md", "---\n- done\n- failed\n---\n# Refresh\n")
    with pytest.raises(InstanceError, match=r"skills/refresh/SKILL\.md.*mapping"):
        load()


def test_a_node_file_with_unreadable_frontmatter_names_the_file(broken, load):
    broken("skills/refresh/SKILL.md", "---\nname: [refresh\n---\n# Refresh\n")
    with pytest.raises(InstanceError, match=r"skills/refresh/SKILL\.md"):
        load()


def test_bare_on_and_off_are_read_as_on_and_off(broken, load):          # Review Focus 3, R4
    broken.frontmatter("refresh", improvisation="off")                  # written as a bare word in the file
    assert load().nodes["refresh"].improvisation == "off"
    assert load().topology["improvisation"]["setting"] == "on"          # the fixture writes it quoted
    broken.frontmatter("refresh", improvisation="on")
    assert load().nodes["refresh"].improvisation == "on"
    text = (broken.root / "topology.yaml").read_text().replace('setting: "on"', "setting: off")
    broken("topology.yaml", text)
    assert load().topology["improvisation"]["setting"] == "off"


def test_a_node_without_an_improvisation_line_has_none(instance):
    assert instance.nodes["refresh"].improvisation is None




def test_a_node_file_that_is_missing_names_the_file(broken, load):
    (broken.root / "skills" / "plain" / "SKILL.md").unlink()
    with pytest.raises(InstanceError, match=r"skills/plain/SKILL\.md"):
        load()


def test_a_key_written_twice_is_refused(broken, load):                   # Review Focus 4
    broken.append("instance.yaml", "  count_words: functions:read_ledger\n")
    with pytest.raises(InstanceError, match=r"instance\.yaml.*count_words"):
        load()




def test_a_key_written_twice_in_a_node_file_names_the_file(broken, load):
    path = broken.root / "skills" / "plain" / "SKILL.md"
    path.write_text(path.read_text().replace("inputs: {}", "inputs: {}\ninputs: {}", 1))
    with pytest.raises(InstanceError, match=r"skills/plain/SKILL\.md.*inputs"):
        load()


def test_schema_violation_names_file_and_field(broken, load):            # INST-1
    broken.remove_key("instance.yaml", "entry")
    with pytest.raises(InstanceError, match=r"instance\.yaml.*entry"):
        load()


def test_a_topology_violation_names_the_file(broken, load):
    text = (broken.root / "topology.yaml").read_text()
    broken("topology.yaml", text.replace("exits:\n  done: route\n  declined: route\n  failed: route\n", ""))
    with pytest.raises(InstanceError, match=r"topology\.yaml.*exits"):
        load()


def test_a_node_context_outside_the_enum_names_file_and_field(broken, load):
    broken.frontmatter("plain", context="everything")
    with pytest.raises(InstanceError, match=r"skills/plain/SKILL\.md.*context"):
        load()


def test_a_missing_policy_file_names_the_file(broken, load):
    (broken.root / "POLICY.md").unlink()
    with pytest.raises(InstanceError, match=r"POLICY\.md"):
        load()


def test_a_missing_instance_file_names_the_file(broken, load):
    (broken.root / "instance.yaml").unlink()
    with pytest.raises(InstanceError, match=r"instance\.yaml"):
        load()


ECHO = '''
from agent_core.contracts.registry import register


@register("tool_source", "echo_t4")
class Echo:
    pass
'''


def _with_echo(broken, provider="echo_t4"):
    broken("providers_echo.py", ECHO)
    broken.append("instance.yaml", f"providers: [providers_echo.py]\nsources:\n  echo:\n    provider: {provider}\n    prefix: hi\n")


def test_providers_are_loaded_and_sources_kept(broken, load):
    _with_echo(broken)
    instance = load()
    assert instance.providers == ("providers_echo.py",)
    assert instance.sources == {"echo": {"provider": "echo_t4", "prefix": "hi"}}
    assert "echo_t4" in REGISTERED["tool_source"]


def test_a_source_naming_an_unregistered_provider_is_refused(broken, load):
    _with_echo(broken, provider="ehco")
    with pytest.raises(InstanceError) as e:
        load()
    assert str(e.value) == 'instance.yaml: source "echo": no tool source `ehco`; tool sources are: echo_t4'


@pytest.mark.parametrize("builtin", ["servers", "tools"])
def test_a_source_may_not_name_a_built_in_source(broken, load, builtin):
    _with_echo(broken, provider=builtin)
    with pytest.raises(InstanceError) as e:
        load()
    assert f"no tool source `{builtin}`" in str(e.value) and str(e.value).endswith("tool sources are: echo_t4")


def test_a_server_declared_by_url_loads(broken, load):
    text = (broken.root / "instance.yaml").read_text().replace(
        "  web: {command: python, args: [../servers/flaky_server.py]}", "  web: {url: \"http://127.0.0.1:9/mcp\"}")
    broken("instance.yaml", text)
    assert load().servers["web"] == {"url": "http://127.0.0.1:9/mcp"}


@pytest.mark.parametrize("entry", ["{args: [x]}", "{command: python, url: \"http://h/mcp\"}"])
def test_a_server_with_neither_or_both_command_and_url_is_refused(broken, load, entry):
    text = (broken.root / "instance.yaml").read_text().replace(
        "{command: python, args: [../servers/flaky_server.py]}", entry)
    broken("instance.yaml", text)
    with pytest.raises(InstanceError, match=r"instance\.yaml.*servers\.web"):
        load()
