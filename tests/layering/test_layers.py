import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
PKG = SRC / "agent_core"
SDKS = {"langchain", "langgraph", "langchain_core", "langchain_anthropic", "anthropic", "openai", "agents", "google", "agno", "crewai"}
PROVIDERS = {"backends", "context", "tools", "resources", "stores", "person"}


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
    assert ("agent_core.tools", 0) in imports_of("from agent_core import tools", core)
    assert ("agent_core.core", 0) in imports_of("from agent_core import core", ["agent_core", "tools"])
    assert ("agent_core.tools", 2) in imports_of("from .. import tools", core)
    assert ("agent_core.core.x", 2) in imports_of("from ..core import x", ["agent_core", "tools"])
    assert ("langchain", 0) in imports_of("from langchain import x", core)


def test_contracts_import_nothing_of_ours_and_no_sdk():  # LAYER-4
    for file in files("contracts"):
        for module, level in imports(file):
            assert module.split(".")[0] not in SDKS, file
            assert not module.startswith("agent_core.") or module.startswith("agent_core.contracts"), file


def test_core_imports_contracts_only():  # LAYER-2
    for file in files("core"):
        for module, level in imports(file):
            assert module.split(".")[0] not in SDKS, file
            assert not any(module.startswith(f"agent_core.{p}") for p in PROVIDERS), file


def test_providers_do_not_import_the_core():  # LAYER-3
    for layer in PROVIDERS:
        for file in files(layer):
            for module, level in imports(file):
                assert not module.startswith("agent_core.core"), file


def test_only_a_backend_imports_an_sdk():
    for layer in PROVIDERS - {"backends"}:
        for file in files(layer):
            assert not {m.split(".")[0] for m, _ in imports(file)} & SDKS, file
