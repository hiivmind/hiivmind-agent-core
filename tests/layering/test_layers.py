import ast
import re
import tomllib
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
PKG = SRC / "agent_core"
SDKS = {"langchain", "langgraph", "langchain_core", "langchain_anthropic", "anthropic", "openai", "langchain_openai", "agents", "google", "agno", "crewai"}
PROVIDERS = {"backends", "journals", "person", "resources", "context"}
HELPERS = {"helpers"}


def files(layer):
    yield from sorted((PKG / layer).rglob("*.py"))


def imports(path) -> list[tuple[str, int]]:
    """(absolute module, relative level) of each import in the file."""
    rel = path.relative_to(SRC).with_suffix("")
    return imports_of(path.read_text(), list(rel.parts[:-1]))


def imports_of(source: str, package: list[str]) -> list[tuple[str, int]]:
    """Imports in source; from-imports also yield each qualified imported name."""
    out = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            out += [(a.name, 0) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - (node.level - 1)]
                if node.module:
                    base = base + node.module.split(".")
            else:
                base = (node.module or "").split(".") if node.module else []
            if base:
                out.append((".".join(base), node.level))
            out += [(".".join(base + [a.name]), node.level) for a in node.names if a.name != "*"]
    return out


def test_imports_see_qualified_from_import_names():
    core = ["agent_core", "core"]
    assert ("agent_core.helpers", 0) in imports_of("from agent_core import helpers", core)
    assert ("agent_core.core", 0) in imports_of("from agent_core import core", ["agent_core", "helpers"])
    assert ("agent_core.helpers", 2) in imports_of("from .. import helpers", core)
    assert ("agent_core.core.x", 2) in imports_of("from ..core import x", ["agent_core", "helpers"])
    assert ("langchain", 0) in imports_of("from langchain import x", core)


def top(file):
    return {m.split(".")[0] for m, _ in imports(file)}


def ours(file):
    return [m for m, _ in imports(file) if m == "agent_core" or m.startswith("agent_core.")]


def test_contracts_import_nothing_of_ours_and_no_sdk():  # FAC-2, LAYER-4
    for file in files("contracts"):
        assert not top(file) & SDKS, file
        for module in ours(file):
            assert module == "agent_core.contracts" or module.startswith("agent_core.contracts."), file


def test_core_imports_contracts_only():  # LAYER-2
    for file in files("core"):
        assert not top(file) & SDKS, file
        for module in ours(file):
            assert not any(module == f"agent_core.{p}" or module.startswith(f"agent_core.{p}.") for p in PROVIDERS | HELPERS), file


def test_helpers_import_contracts_only():
    for layer in HELPERS:
        for file in files(layer):
            for module in ours(file):
                assert module == "agent_core.contracts" or module.startswith("agent_core.contracts."), file


def test_providers_do_not_import_the_core():  # LAYER-3
    for layer in PROVIDERS:
        for file in files(layer):
            for module in ours(file):
                assert module != "agent_core.core" and not module.startswith("agent_core.core."), file


def test_only_a_backend_imports_an_sdk():
    for layer in (PROVIDERS | HELPERS | {"core", "contracts"}) - {"backends"}:
        for file in files(layer):
            assert not top(file) & SDKS, file


def test_only_the_dbos_journal_imports_dbos():  # RESUME-6, LAYER-2
    for file in sorted(PKG.rglob("*.py")):
        if file != PKG / "journals" / "dbos.py":
            assert "dbos" not in top(file), file


def test_only_the_mcp_helper_imports_mcp():
    for file in sorted(PKG.rglob("*.py")):
        if file != PKG / "helpers" / "mcp.py":
            assert "mcp" not in top(file), file


def test_the_cli_imports_only_agent_core():  # FAC-4
    cli = PKG / "cli.py"
    if not cli.exists():
        return
    for module in ours(cli):
        assert module == "agent_core", cli


def test_the_layering_walk_sees_files():
    assert (PKG / "contracts" / "__init__.py").exists()
    assert {p.name for p in PKG.iterdir() if p.is_dir()} >= {"contracts", "core", "helpers", "backends", "journals", "person", "resources", "context", "assets"}


def test_nothing_calls_a_node_a_skill():  # LNG-1
    allowed = PKG / "contracts" / "matrix.py"
    for file in sorted(PKG.rglob("*")):
        if not file.is_file() or file.suffix == ".pyc":
            continue
        text = file.read_text()
        assert "SKILL.md" not in text, file
        if file != allowed:
            assert not re.search(r"skill", text, re.I), file
        else:
            leftover = re.sub(r"\"skills\"", "", text, flags=re.I)
            assert not re.search(r"skill", leftover, re.I), file


def test_the_core_depends_on_no_agent_sdk_and_no_blueprint():  # CORE-5
    deps = tomllib.loads((PKG.parents[1] / "pyproject.toml").read_text())["project"]["dependencies"]
    names = [re.split(r"[<>=!~\[; ]", d, maxsplit=1)[0].lower() for d in deps]
    for name in names:
        assert not name.startswith(("langchain", "langgraph", "hiivmind-blueprint")), name
        assert name not in {"anthropic", "openai"}, name


def test_the_core_knows_no_domain():  # CORE-4a
    for file in sorted(PKG.rglob("*")):
        if file.is_file() and file.suffix != ".pyc":
            assert "corpus" not in file.read_text().lower(), file
