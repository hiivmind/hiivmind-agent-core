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
    package = list(rel.parts[:-1])
    out = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            out += [(a.name, 0) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - (node.level - 1)]
                if node.module:
                    base = base + node.module.split(".")
                    out.append((".".join(base), node.level))
                else:
                    out += [(".".join(base + [a.name]), node.level) for a in node.names]
            else:
                out.append((node.module or "", 0))
    return out


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
