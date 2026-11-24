"""The instance's files: instance.yaml, the topology, the nodes and the policy."""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from yaml.constructor import ConstructorError

from agent_core.contracts.resources import ResourceSource
from agent_core.contracts.topology import (
    END,
    Check,
    FanOut,
    FragmentDef,
    Link,
    NodeContract,
    SequenceDef,
    Step,
    Target,
    ToolList,
    Topology,
)

SCHEMAS = Path(__file__).parent / "schemas"


@dataclass(frozen=True)
class NodeDef:
    contract: NodeContract
    file: str
    description: str
    input_docs: dict
    output_schemas: dict
    allowed_tools: tuple[str, ...]
    preconditions: tuple[Check, ...]
    context: str
    body: str
    # The checks of the outputs `exit` carries, built once here (JOB-7a, CD-11): with `done`, and with another outcome,
    # which may carry a `reason` and need not give every output.
    outputs_on_done: Draft202012Validator = field(compare=False, repr=False)
    outputs_otherwise: Draft202012Validator = field(compare=False, repr=False)


def _outputs(outputs: dict, done: bool) -> Draft202012Validator:
    return Draft202012Validator({
        "type": "object",
        "properties": outputs if done else {**outputs, "reason": {"type": "string"}},
        "additionalProperties": False,
        "required": list(outputs) if done else [],
    })


@dataclass(frozen=True)
class Instance:
    root: Path
    name: str
    core: int
    backend: str
    policy: str                       # the text of the policy file
    topology: Topology
    nodes: Mapping[str, NodeDef]
    servers: Mapping[str, dict]
    functions: Mapping[str, str]
    settings: dict | None
    improvisation: str | None         # "on" or "off", from the topology; None when it names none


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
    error = max(validator.iter_errors(data), key=lambda e: len(e.absolute_path), default=None)
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


def _check(entry: dict) -> Check:
    return Check(entry["tool"], entry.get("args") or {}, entry["message"], entry.get("outcome"))


def _node(resources: ResourceSource, name: str, file: str) -> NodeDef:
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
    inputs, outputs = front.get("inputs") or {}, front.get("outputs") or {}
    return NodeDef(
        contract=NodeContract(name, tuple(inputs), tuple(outputs), tuple(front.get("exits") or ())),
        file=file,
        description=front["description"],
        input_docs=inputs,
        output_schemas=outputs,
        allowed_tools=tuple(front.get("allowed-tools") or ()),
        preconditions=tuple(_check(c) for c in front.get("preconditions") or ()),
        context=front.get("context", "none"),
        body=body,
        outputs_on_done=_outputs(outputs, done=True),
        outputs_otherwise=_outputs(outputs, done=False),
    )


class _Targets:
    """Turns the YAML of a transition target into a contract value, checking the names it uses."""

    def __init__(self, file: str, nodes: Mapping[str, NodeDef], fragments: Mapping[str, dict] | None):
        """`fragments` None: a fragment's own targets, which name nodes only."""
        self.file, self.nodes, self.fragments = file, nodes, fragments

    def step_name(self, name: str) -> str:
        if name not in self.nodes and name not in (self.fragments or {}):
            what = "node" if self.fragments is None else "node or fragment"
            raise InstanceError(f"{self.file}: no {what} `{name}`")
        return name

    def fan_out(self, entry: dict) -> FanOut:
        node = entry["fan_out"]
        if node not in self.nodes:
            raise InstanceError(f"{self.file}: no node `{node}`")
        over = entry["over"]
        if isinstance(over, dict):
            over = ToolList(over["tool"], over.get("args") or {})
        return FanOut(node, over, entry["as"], entry["into"], entry.get("max_concurrency", 4))

    def target(self, entry) -> Target:
        if isinstance(entry, str):
            return END if entry == END else Step(self.step_name(entry))
        if "link" in entry:
            return Link(entry["link"])
        if "fan_out" in entry:
            return self.fan_out(entry)
        return Step(self.step_name(entry["node"]), dict(entry["inputs"]))

    def start(self, entry) -> Target:
        return self.fan_out(entry) if isinstance(entry, dict) else Step(self.step_name(entry))

    def transitions(self, table: Mapping[str, dict]) -> dict:
        return {source: {outcome: self.target(t) for outcome, t in row.items()} for source, row in table.items()}


def _sequences(raw: Mapping[str, dict], targets: _Targets) -> dict[str, SequenceDef]:
    return {
        name: SequenceDef(
            name=name,
            description=seq["description"],
            start=targets.start(seq["start"]),
            inputs=seq.get("inputs") or {},
            checks=tuple(_check(c) for c in seq.get("checks") or ()),
            transitions=targets.transitions(seq["transitions"]),
        )
        for name, seq in raw.items()
    }


def _fragments(raw: Mapping[str, dict], targets: _Targets) -> dict[str, FragmentDef]:
    return {
        name: FragmentDef(
            name=name,
            inputs=tuple(f["inputs"]),
            outputs=tuple(f["outputs"]),
            exits=tuple(f["exits"]),
            start=targets.start(f["start"]),
            transitions=targets.transitions(f["transitions"]),
        )
        for name, f in raw.items()
    }


def load_instance(instance_yaml: Path, resources: ResourceSource) -> Instance:
    file = Path(instance_yaml).name
    data = _yaml_file(resources, file, "instance")
    entry = data["entry"]
    raw = _yaml_file(resources, entry, "topology")
    nodes: dict[str, NodeDef] = {}
    for item in raw["nodes"]:
        if item["name"] in nodes:
            raise InstanceError(f"{entry}: the node `{item['name']}` is listed twice")
        nodes[item["name"]] = _node(resources, item["name"], item["path"])
    raw_fragments = raw.get("fragments") or {}
    targets = _Targets(entry, nodes, raw_fragments)
    topology = Topology(
        nodes={name: n.contract for name, n in nodes.items()},
        sequences=_sequences(raw.get("sequences") or {}, targets),
        fragments=_fragments(raw_fragments, _Targets(entry, nodes, None)),
    )
    return Instance(
        root=Path(instance_yaml).resolve().parent,
        name=data["name"],
        core=data["core"],
        backend=data["backend"],
        policy=_read(resources, data["policy"]),
        topology=topology,
        nodes=nodes,
        servers=data.get("servers") or {},
        functions=data.get("tools") or {},
        settings=data.get("settings"),
        improvisation=_improvisation((raw.get("improvisation") or {}).get("setting")),
    )
