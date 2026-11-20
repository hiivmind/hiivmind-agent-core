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


def sdk_imports(source: str) -> set[str]:
    return {m.split(".")[0] for m, _ in imports_of(source, ["agent_core"])} & SDKS


def test_only_a_backend_imports_an_sdk():
    for file in sorted(PKG.rglob("*.py")):
        if (PKG / "backends") not in file.parents:
            assert not top(file) & SDKS, file


def test_the_sdk_gate_rejects_an_sdk_import():
    assert sdk_imports("import openai") == {"openai"}
    assert sdk_imports("from langchain_openai import ChatOpenAI") == {"langchain_openai"}
    assert sdk_imports("import json") == set()


def test_only_the_dbos_journal_imports_dbos():  # RESUME-6, LAYER-2
    for file in sorted(PKG.rglob("*.py")):
        if file != PKG / "journals" / "dbos.py":
            assert "dbos" not in top(file), file


def test_only_the_mcp_helper_imports_mcp():
    for file in sorted(PKG.rglob("*.py")):
        if file != PKG / "helpers" / "mcp.py":
            assert "mcp" not in top(file), file


def cli_violations(source: str) -> list[str]:
    """Imports of ours that are neither `agent_core` nor its public `open`."""
    out = []
    for module, _ in imports_of(source, ["agent_core"]):
        if (module == "agent_core" or module.startswith("agent_core.")) and module not in ("agent_core", "agent_core.open"):
            out.append(module)
    return out


def test_the_cli_imports_only_agent_core():  # FAC-4
    cli = PKG / "cli.py"
    if cli.exists():
        assert not cli_violations(cli.read_text()), cli


def test_the_cli_gate_allows_the_public_open_and_rejects_internals():
    assert cli_violations("from agent_core import open") == []
    assert cli_violations("import agent_core") == []
    assert cli_violations("from agent_core import core") == ["agent_core.core"]
    assert cli_violations("from agent_core.core.facade import x") != []
    assert cli_violations("import agent_core.contracts") != []


def test_the_layering_walk_sees_files():
    assert (PKG / "contracts" / "__init__.py").exists()
    assert {p.name for p in PKG.iterdir() if p.is_dir()} >= {"contracts", "core", "helpers", "backends", "journals", "person", "resources", "context", "assets"}


def f22_title(source: str) -> ast.Constant | None:
    """The string constant "skills" in the value of `F22 = ...` in the class `Feature`: F22's title, the one allowed use."""
    for cls in ast.parse(source).body:
        if isinstance(cls, ast.ClassDef) and cls.name == "Feature":
            for node in cls.body:
                if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "F22" for t in node.targets):
                    for sub in ast.walk(node.value):
                        if isinstance(sub, ast.Constant) and sub.value == "skills":
                            return sub
    return None


def blank(source: str, node: ast.Constant) -> str:
    """The source with exactly the node's span replaced by spaces (columns are UTF-8 byte offsets)."""
    lines = [line.encode() for line in source.splitlines(keepends=True)]
    for n in range(node.lineno, node.end_lineno + 1):
        start = node.col_offset if n == node.lineno else 0
        end = node.end_col_offset if n == node.end_lineno else len(lines[n - 1])
        lines[n - 1] = lines[n - 1][:start] + b" " * (end - start) + lines[n - 1][end:]
    return b"".join(lines).decode()


def skill_violations(text: str, is_matrix: bool) -> list[str]:
    """Uses of the word `skill`; in matrix.py, F22's title constant alone is exempt."""
    bad = ["SKILL.md"] if "SKILL.md" in text else []
    title = f22_title(text) if is_matrix else None
    if title:
        text = blank(text, title)
    return bad + [line for line in text.splitlines() if re.search(r"skill", line, re.I)]


def test_nothing_calls_a_node_a_skill():  # LNG-1
    matrix = PKG / "contracts" / "matrix.py"
    for file in sorted(PKG.rglob("*")):
        if file.is_file() and file.suffix != ".pyc":
            assert not skill_violations(file.read_text(), file == matrix), file


def test_the_language_gate_allows_only_f22s_title():
    ok = 'class Feature:\n    F22 = Entry("F22", "skills")\n'
    assert skill_violations(ok, True) == []
    assert skill_violations('class Feature:\n    F22 = Entry(\n        "F22",\n        "skills")\n', True) == []
    assert skill_violations('class Feature:\n    node_directory = "skills"  # F22\n', True) != []
    assert skill_violations('class Feature:\n    F22 = Entry("F22", "skills")  # skills\n', True) != []
    assert skill_violations('class Feature:\n    F22 = Entry("F22", "skills"); node_directory = "skills"\n', True) != []
    assert skill_violations('class Feature:\n    F22 = Entry("F22", "skills", "skills")\n', True) != []
    assert skill_violations(ok + '    F23 = "skills"\n', True) != []
    assert skill_violations('class Other:\n    F22 = "skills"\n', True) != []
    assert skill_violations('F22 = "skills"\n', True) != []
    assert skill_violations(ok, False) != []
    assert skill_violations("see SKILL.md", False) != []
    assert skill_violations("a node's path", False) == []


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


def test_importing_a_contract_module_does_not_import_the_core():  # LAYER-2: a fresh process, so no earlier import hides it
    import subprocess
    import sys

    for module in sorted(p.stem for p in (PKG / "contracts").glob("*.py") if p.stem != "__init__"):
        code = f"import agent_core.contracts.{module}, sys; assert 'agent_core.core.facade' not in sys.modules"
        done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        assert done.returncode == 0, (module, done.stderr[-1000:])


def test_the_package_still_exposes_open_and_its_names_lazily():
    import subprocess
    import sys

    code = (
        "import agent_core, sys; assert 'agent_core.core.facade' not in sys.modules;"
        "assert agent_core.open.__module__ == 'agent_core.core.facade';"
        "assert agent_core.RunCannotStart.__name__ == 'RunCannotStart' and agent_core.Outcome and agent_core.FeatureNotSupported and agent_core.ToolServerError"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-1000:]


PROVIDER_DIR = PKG / "backends" / "langgraph" / "providers"


def test_only_the_openai_provider_imports_the_sign_in_package():  # CRED-16
    for file in sorted(PKG.rglob("*.py")):
        if file != PROVIDER_DIR / "openai.py":
            assert "mountainash_auth_openai" not in top(file), file


def reads_credential(source: str) -> bool:
    return any(isinstance(n, ast.Attribute) and n.attr == "CREDENTIAL" for n in ast.walk(ast.parse(source)))


def test_only_provider_modules_read_the_credential():  # CRED-16
    allowed = {PROVIDER_DIR / "openai.py", PROVIDER_DIR / "anthropic.py"}
    for file in sorted(PKG.rglob("*.py")):
        if file not in allowed:
            assert not reads_credential(file.read_text()), file


def test_the_credential_gate_sees_an_attribute_read():
    assert reads_credential("settings.CREDENTIAL == 'account'")
    assert not reads_credential("CREDENTIAL: str = 'env'")
