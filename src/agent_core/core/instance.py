"""The instance's files: instance.yaml, the topology, the nodes and the policy."""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from yaml.constructor import ConstructorError

from agent_core.contracts.registry import REGISTERED
from agent_core.contracts.resources import ResourceSource
from agent_core.core.registry import PROVIDERS, load_providers

SCHEMAS = Path(__file__).parent / "schemas"
BUILT_IN_SOURCES = ("servers", "tools")


@dataclass(frozen=True)
class Node:
    name: str
    file: str
    description: str
    inputs: dict
    outputs: dict
    exits: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    improvisation: str | None
    preconditions: tuple[dict, ...]
    context: str
    body: str


@dataclass(frozen=True)
class Instance:
    root: Path
    name: str
    core: int
    backend: str
    topology: dict
    policy: str                       # the text of POLICY.md
    nodes: dict[str, Node]
    servers: dict
    functions: dict[str, str]
    settings: dict | None
    providers: tuple[str, ...] = ()   # instance files that register providers
    sources: dict[str, dict] = field(default_factory=dict)   # key -> {provider: <tool source>, ...}; tools are named <key>__<tool>


class InstanceError(ValueError):
    """Each message names the file the problem is in."""


class _Loader(yaml.SafeLoader):
    """YAML that refuses a key written twice."""


def _mapping(loader: _Loader, node: yaml.MappingNode, deep: bool = False) -> dict:
    seen = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in seen:
            raise ConstructorError(None, None, f"the key `{key}` is written twice", key_node.start_mark)
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


_Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def _parse(text: str, file: str):
    try:
        return yaml.load(text, Loader=_Loader)
    except yaml.YAMLError as e:
        problem = getattr(e, "problem", None) or str(e)
        mark = getattr(e, "problem_mark", None)
        where = f" (line {mark.line + 1})" if mark else ""
        raise InstanceError(f"{file}: {problem}{where}") from None


def _validate(data, schema: str, file: str) -> None:
    validator = Draft202012Validator(json.loads((SCHEMAS / f"{schema}.schema.json").read_text()))
    error = max(validator.iter_errors(data), key=lambda e: -len(e.path), default=None)
    if error is not None:
        field_path = ".".join(str(p) for p in error.absolute_path)
        raise InstanceError(f"{file}: {field_path + ': ' if field_path else ''}{error.message}")


def _read(resources: ResourceSource, file: str) -> str:
    try:
        return resources.read(file)
    except FileNotFoundError:
        raise InstanceError(f"{file}: no such file") from None


def _yaml_file(resources: ResourceSource, file: str, schema: str) -> dict:
    data = _parse(_read(resources, file), file)
    if not isinstance(data, dict):
        raise InstanceError(f"{file}: must be a mapping")
    _validate(data, schema, file)
    return data


def _improvisation(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "on" if value else "off"
    return value


def _node(resources: ResourceSource, name: str, directory: str) -> Node:
    file = f"{directory.rstrip('/')}/SKILL.md"
    text = _read(resources, file)
    if not text.startswith("---\n"):
        raise InstanceError(f"{file}: the file must begin with a frontmatter block between `---` lines")
    closing = re.search(r"^---[ \t]*(?:\n|$)", text[4:], re.MULTILINE)
    if closing is None:
        raise InstanceError(f"{file}: the frontmatter block is not closed by a `---` line")
    head, body = text[4:][: closing.start()], text[4:][closing.end():]
    front = _parse(head, file)
    if not isinstance(front, dict):
        raise InstanceError(f"{file}: the frontmatter must be a mapping")
    _validate(front, "node", file)
    if front["name"] != name:
        raise InstanceError(f"{file}: the node is named `{front['name']}` but the topology names it `{name}`")
    return Node(
        name=name,
        file=file,
        description=front["description"],
        inputs=front.get("inputs") or {},
        outputs=front.get("outputs") or {},
        exits=tuple(front.get("exits") or ()),
        allowed_tools=tuple(front.get("allowed-tools") or ()),
        improvisation=_improvisation(front.get("improvisation")),
        preconditions=tuple(front.get("preconditions") or ()),
        context=front.get("context", "none"),
        body=body,
    )


def _tool_sources() -> list[str]:
    names = set(PROVIDERS.get("tool_source", {})) | set(REGISTERED.get("tool_source", {}))
    return sorted(names - set(BUILT_IN_SOURCES))


def _check_keys(data: dict, file: str) -> None:
    """`<key>__<tool>` names a tool, so a key may belong to one of servers, tools and sources only."""
    seen: dict[str, str] = {}
    for section in ("servers", "tools", "sources"):
        for key in data.get(section) or {}:
            if key in seen:
                raise InstanceError(f"{file}: the key `{key}` is in both `{seen[key]}` and `{section}`")
            seen[key] = section
    for key, source in (data.get("sources") or {}).items():
        if source["provider"] not in _tool_sources():
            raise InstanceError(
                f"{file}: source \"{key}\": no tool source `{source['provider']}`; "
                f"tool sources are: {', '.join(_tool_sources())}"
            )


def load_instance(instance_yaml: Path, resources: ResourceSource) -> Instance:
    file = Path(instance_yaml).name
    data = _yaml_file(resources, file, "instance")
    for key in ("servers", "tools", "sources"):
        data.setdefault(key, {})
    providers = tuple(data.get("providers") or ())
    if providers:
        root = Path(instance_yaml).resolve().parent
        try:
            load_providers(root, providers)
        except FileNotFoundError as e:
            raise InstanceError(f"{file}: provider file not found: {e.filename or e}") from None
    _check_keys(data, file)
    topology = _yaml_file(resources, data["entry"], "topology")
    if "improvisation" in topology and "setting" in topology["improvisation"]:
        topology["improvisation"]["setting"] = _improvisation(topology["improvisation"]["setting"])
    nodes: dict[str, Node] = {}
    for entry in topology["nodes"]:
        if entry["name"] in nodes:
            raise InstanceError(f"{data['entry']}: the node `{entry['name']}` is listed twice")
        nodes[entry["name"]] = _node(resources, entry["name"], entry["path"])
    return Instance(
        root=Path(instance_yaml).resolve().parent,
        name=data["name"],
        core=data["core"],
        backend=data["backend"],
        topology=topology,
        policy=_read(resources, data["policy"]),
        nodes=nodes,
        servers=data["servers"],
        functions=data["tools"],
        settings=data.get("settings"),
        providers=providers,
        sources=data["sources"],
    )
