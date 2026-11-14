"""What the acceptance suite runs on: `agent-core job` in a subprocess with the LangGraph backend, a trace of the
requests at the provider's HTTP client, and readers for what the run left in its directory.

The trace is switched on by an environment variable this plugin sets for the subprocess (`traced_cli.py` reads it).
The provider's key is not read here: the subprocess inherits it from the shell that started pytest.
Run directories are kept under `acceptance-runs/<date>/<model>/<test>/`.
"""

import json
import os
import pty
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest

from agent_core.core.registry import backend

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "fixtures"
INSTANCE = FIXTURES / "instance"
ALPHA = INSTANCE / "config" / "alpha.yaml"
LAUNCHER = Path(__file__).with_name("traced_cli.py")
TRACE_ENV = "AGENT_CORE_WIRE_TRACE"
PROCEDURE_LINE = re.compile(r"# Procedure of the node that is running: `([^`]+)`")


def jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


@dataclass
class Call:
    """A call the model made in one node run, with the result it was given (None for a call the run ended on)."""

    name: str
    input: dict
    result: str | None


def _result_text(content) -> str:
    return content if isinstance(content, str) else "".join(b.get("text", "") for b in content)


@dataclass
class Ran:
    """What one run of the command left: its exit code, standard output, `record.json` ({} if none), and its directory."""

    code: int
    out: str
    err: str
    dir: Path

    @property
    def record(self) -> dict:
        file = self.dir / "record.json"
        return json.loads(file.read_text()) if file.exists() else {}

    @property
    def summary(self) -> dict:
        summary = self.record.get("summary")
        return summary if isinstance(summary, dict) else {}

    @property
    def returned(self) -> list[dict]:
        """What each `run_node` of the job returned, as the job script put it in its summary."""
        return self.summary.get("returned", [])

    @property
    def first(self) -> dict:
        return self.returned[0] if self.returned else {}

    @property
    def trace(self) -> list[dict]:
        """The requests made to the provider, in the order they were sent, each with the node it ran."""
        lines = sorted(jsonl(self.dir / "trace.jsonl"), key=lambda line: line["ts"])
        for line in lines:
            found = PROCEDURE_LINE.search(line["system"])
            line["node"] = found.group(1) if found else None
        return lines

    def requests_of(self, node: str) -> list[dict]:
        return [q for q in self.trace if q["node"] == node]

    def calls_of(self, node: str) -> list[Call]:
        """Every call the model made in the run of `node`, in order: those in the last request's conversation, then those
        of its answer."""
        requests = self.requests_of(node)
        if not requests:
            return []
        last = requests[-1]
        results = {
            block["tool_use_id"]: _result_text(block.get("content") or "")
            for message in last["messages"]
            if message["role"] == "user" and not isinstance(message["content"], str)
            for block in message["content"]
            if block.get("type") == "tool_result"
        }
        made = [
            Call(block["name"], block["input"], results.get(block["id"]))
            for message in last["messages"]
            if message["role"] == "assistant" and not isinstance(message["content"], str)
            for block in message["content"]
            if block.get("type") == "tool_use"
        ]
        return made + [Call(c["name"], c["input"], None) for c in ((last["response"] or {}).get("calls") or [])]

    def files(self) -> list[str]:
        return sorted(p.name for p in self.dir.iterdir())

    def shell_commands(self) -> list[str]:
        return [c["args"]["command"] for c in jsonl(self.dir / "tool_calls.jsonl") if c["tool"] == "shell"]

    def server_calls(self, tool: str, server: str | None = None) -> list[dict]:
        """What a tool server saw. The shell server's lines carry no server name; the web server's carry `web`."""
        return [c for c in jsonl(self.dir / "tool_calls.jsonl") if c["tool"] == tool and c.get("server") == server]

    def function_calls(self, tool: str) -> list[dict]:
        return [c for c in jsonl(self.dir / "function_calls.jsonl") if c["tool"] == tool]


class Accept:
    """Runs jobs of the fixture instance. Each run has a directory of its own under this test's directory."""

    def __init__(self, directory: Path):
        self.dir = directory

    def run_dir(self, sub: str | None) -> Path:
        run_dir = self.dir / (sub or "run")
        shutil.rmtree(run_dir, ignore_errors=True)
        run_dir.mkdir(parents=True)
        return run_dir

    def edited(self, sub: str, *, replace: tuple[str, str] | None = None, tool: str | None = None) -> Path:
        """A copy of the fixture instance with its servers beside it, edited as asked: a text and its replacement, or
        a line added under `tools:`. Returns the path of its `instance.yaml`."""
        base = self.dir / f"{sub}_instance"
        shutil.rmtree(base, ignore_errors=True)
        ignore = shutil.ignore_patterns("__pycache__")
        shutil.copytree(INSTANCE, base / "instance", ignore=ignore)
        shutil.copytree(FIXTURES / "servers", base / "servers", ignore=ignore)
        text = (base / "instance" / "instance.yaml").read_text()
        if replace is not None:
            assert replace[0] in text
            text = text.replace(*replace)
        lines = text.splitlines()
        if tool is not None:
            lines.insert(lines.index("tools:") + 1, f"  {tool}")
        (base / "instance" / "instance.yaml").write_text("\n".join(lines) + "\n")
        return base / "instance" / "instance.yaml"

    def command(self, name: str, run_dir: Path, instance: Path | None, flags) -> list[str]:
        return [
            sys.executable, str(LAUNCHER), "job", str(instance or INSTANCE / "instance.yaml"), name,
            "--settings", str(ALPHA), "--backend", "langgraph", "--run-dir", str(run_dir), *flags,
        ]

    def environment(self, run_dir: Path) -> dict:
        return {**os.environ, TRACE_ENV: str(run_dir / "trace.jsonl")}

    def run(self, name, *, sub=None, ready=False, flags=(), typed=None, instance=None) -> Ran:
        """Run one job in a new process. `ready` meets the `gated` nodes' precondition first. `typed` runs the job
        with a terminal as its standard input and types that line into it."""
        run_dir = self.run_dir(sub)
        if ready:
            (run_dir / "alpha.ready").touch()
        command, env = self.command(name, run_dir, instance, flags), self.environment(run_dir)
        if typed is None:
            done = subprocess.run(command, capture_output=True, text=True, cwd=REPO, env=env, stdin=subprocess.DEVNULL, timeout=900)
            return Ran(done.returncode, done.stdout, done.stderr, run_dir)
        master, slave = pty.openpty()
        child = subprocess.Popen(
            command, stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=REPO, env=env
        )
        os.close(slave)
        os.write(master, (typed + "\n").encode())  # typed ahead; the terminal holds it until the job reads
        try:
            out, err = child.communicate(timeout=900)
        finally:
            os.close(master)
        return Ran(child.returncode, out, err, run_dir)

    def finished(self, code: int, out: str, run_dir: Path) -> Ran:
        """The result of a run the test started itself (`start_at_a_terminal`) and waited for."""
        return Ran(code, out, "", run_dir)

    @staticmethod
    def node_file(name: str) -> str:
        return (INSTANCE / "skills" / name / "SKILL.md").read_text()

    def start_at_a_terminal(self, name: str, sub: str | None = None):
        """Start a job with a terminal as its standard input and return (the process, the terminal's end to type into,
        its run directory). The caller reads the process's standard output and closes the terminal."""
        run_dir = self.run_dir(sub)
        master, slave = pty.openpty()
        with (run_dir / "stderr.txt").open("w") as err:
            child = subprocess.Popen(
                self.command(name, run_dir, None, ()), stdin=slave, stdout=subprocess.PIPE, stderr=err, cwd=REPO,
                env=self.environment(run_dir),
            )
        os.close(slave)
        return child, master, run_dir


@pytest.fixture(scope="session")
def runs_dir() -> Path:
    model = backend("langgraph")[1]().MODEL
    return REPO / "acceptance-runs" / date.today().isoformat() / model


@pytest.fixture
def accept(request, runs_dir) -> Accept:
    directory = runs_dir / re.sub(r"[^\w.-]", "_", request.node.name)
    shutil.rmtree(directory, ignore_errors=True)
    directory.mkdir(parents=True)
    return Accept(directory)
