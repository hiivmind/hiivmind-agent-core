"""What the tests of `agent-core job` share: a copy of a fixture instance, scripts for the scripted backend, and the
command run in a subprocess (so that a crash ends a process, not the test)."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
ALPHA = FIXTURES / "instance" / "config" / "alpha.yaml"
ASK_ONE = """
sequences:
  plain_run:
    description: Run the plain node.
    start: plain
    transitions:
      plain: {done: end, failed: end}
  ask_one:
    description: Ask the person a colour.
    start: asker
    transitions:
      asker: {done: end, failed: end}
"""
PLAIN = [[["exit", {"outcome": "done", "outputs": {"done_work": "plain-work"}}]]]
ASK = [[["ask", {"question": "Which colour?"}]], [["exit", {"outcome": "done", "outputs": {"colour": "red"}}]]]


class Finished:
    """What the command did: its exit code, `record.json` of its run directory ({} if none), its output, its directory."""

    def __init__(self, code: int, record: dict, out: str, run_dir: Path):
        self.code, self.record, self.out, self.run_dir = code, record, out, run_dir

    def __iter__(self):
        return iter((self.code, self.record))


def read_record(run_dir: Path) -> dict:
    file = run_dir / "record.json"
    return json.loads(file.read_text()) if file.exists() else {}


class Jobs:
    """`agent-core job` on a fixture instance (`instance` or `sequences`), run as a subprocess.

    Given `with_tool` (a line added under `tools:`), `with_lines` (text added at the end of `topology.yaml`), `replace`
    (a text of `instance.yaml` and its replacement) or `files` (relative path -> text, written into the copy), the
    instance is a copy in a temporary directory, with the fixture's servers beside it. `scripts` gives the scripted
    backend its scripts (node -> script; `None` removes the node's script); `base` is the directory they start from.
    """

    def __init__(self, tmp_path: Path, fixture: str, base: Path | None = None):
        self.tmp_path, self.fixture, self.base = tmp_path, fixture, base
        self.copied = False
        self.made: dict[str, Path] = {}   # the instances made, by their edits: the same edits give the same copy

    def instance(self, *, with_tool=None, with_lines="", replace=None, files=None) -> Path:
        if not (with_tool or with_lines or replace or files):
            return FIXTURES / self.fixture / "instance.yaml"
        key = repr((with_tool, with_lines, replace, sorted((files or {}).items())))
        if key in self.made:
            return self.made[key]
        root = self.tmp_path / "copy"
        if not self.copied:
            shutil.copytree(FIXTURES, root, ignore=shutil.ignore_patterns("__pycache__", "scripts"))
            self.copied = True
        yaml = root / self.fixture / "instance.yaml"
        if with_tool:
            yaml.write_text(yaml.read_text().replace("tools:\n", f"tools:\n  {with_tool}\n", 1))
        if replace:
            assert replace[0] in yaml.read_text(), replace[0]
            yaml.write_text(yaml.read_text().replace(*replace))
        if with_lines:
            topology = yaml.parent / "topology.yaml"
            topology.write_text(topology.read_text() + with_lines)
        for file, text in (files or {}).items():
            (yaml.parent / file).parent.mkdir(parents=True, exist_ok=True)
            (yaml.parent / file).write_text(text)
        self.made[key] = yaml
        return yaml

    def scripts(self, run: str, scripts: dict | None) -> Path:
        directory = self.tmp_path / f"scripts-{run}"
        directory.mkdir(exist_ok=True)
        if self.base is not None:
            shutil.copytree(self.base, directory, dirs_exist_ok=True)
        for node, script in (scripts or {}).items():
            (directory / f"{node}.json").unlink(missing_ok=True)
            if script is not None:
                (directory / f"{node}.json").write_text(json.dumps(script))
        return directory

    def command(
        self, name, *, run="run", args=(), settings=(), params=None, scripts=None, env=None, **edits
    ) -> tuple[list[str], dict, Path]:
        run_dir = self.tmp_path / run
        command = [sys.executable, "-m", "agent_core.cli", "job", str(self.instance(**edits)), name, "--run-dir", str(run_dir)]
        for file in settings:
            command += ["--settings", str(file)]
        for key, value in (params or {}).items():
            command += ["--param", f"{key}={value}"]
        environment = {  # the fixture's own functions and checks read the run directory from the environment (Q5)
            **os.environ, "AGENT_CORE_SCRIPTED_SCRIPTS": str(self.scripts(run, scripts)), "AGENT_CORE_RUN_DIR": str(run_dir),
            **(env or {}),
        }
        return command + list(args), environment, run_dir

    def __call__(self, name, **options) -> Finished:
        command, environment, run_dir = self.command(name, **options)
        done = subprocess.run(
            command, capture_output=True, text=True, cwd=REPO, env=environment, stdin=subprocess.DEVNULL, timeout=300
        )
        return Finished(done.returncode, read_record(run_dir), done.stdout, run_dir)

    def start(self, name, **options) -> tuple[subprocess.Popen, Path]:
        command, environment, run_dir = self.command(name, **options)
        child = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=REPO, env=environment,
            stdin=subprocess.DEVNULL,
        )
        return child, run_dir
