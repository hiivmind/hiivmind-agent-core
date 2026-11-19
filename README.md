# agent-core

A small Python harness that runs model-driven procedures, called nodes, and walks them as sequences. `agent_core.open(instance)` returns one runtime object; `agent-core job` is a client of it. The core imports no agent framework: each framework sits behind a backend, which is a provider the core is handed by name.

The old tree (v0) is kept at the tag `v0-final`; it is not in this tree.

Design documents (hiivmind-central, 2026-11-18): [architecture](https://github.com/hiivmind/hiivmind-central/blob/main/04.planning/hiivmind-agent-core/superpowers/specs/2026-11-18-agent-core-architecture.md), [requirements](https://github.com/hiivmind/hiivmind-central/blob/main/04.planning/hiivmind-agent-core/superpowers/specs/2026-11-18-agent-core-requirements.md), [layered facade design](https://github.com/hiivmind/hiivmind-central/blob/main/04.planning/hiivmind-agent-core/superpowers/specs/2026-11-18-agent-core-layered-facade-design.md).

## Layers

`src/agent_core/`, each layer importing only the ones named (`tests/layering` checks this by AST):

| Directory | Holds | Imports |
|---|---|---|
| `contracts/` | the protocols and values every layer shares: `Backend`, `Policy`, the topology, the facade's protocols, the events, the matrix of features | nothing of ours, no SDK |
| `core/` | the facade, core policy (one `NodePolicy` per node run), the macro walk's driver, the instance loader, the registry | `contracts/` |
| `helpers/` | the walk (a sequence or a fragment, fan-out), the MCP client | `contracts/` |
| `backends/`, `journals/`, `person/`, `resources/`, `context/` | providers: the scripted backend, the DBOS journal, the terminal and nobody, the folder, the none strategy | `contracts/`, `helpers/` |
| `cli.py` | `agent-core job` | `agent_core` (its public `open`) only |

The core reaches helpers and providers by name through the registry (`core/registry.py` holds module names as strings), so the walk is written once and serves both the macro level (driven by the core, journalled by DBOS) and a fragment (driven by a backend without a graph). `packages/agent-tools/` is a second distribution with the shell server (`shell__run`); the core ships no tools.

The backends and the features each provides are one matrix, `ScriptedBackend.FEATURES` for the scripted backend. `tests/conformance/` holds one test file per feature, run for every backend the registry names, and `tests/test_audit.py` checks the matrix against what those tests did.

## `agent_core.open`

```python
import agent_core

async with agent_core.open("instance.yaml", backend=None, settings=(), params=None, person=None, runs=None) as harness:
    outcome = await harness.nodes.run("lookup", {"name": "alpha"})
    result = await harness.sequences.run("lookup_then_count", {"name": "alpha"})
    result = await harness.sequences.resume(result.run_id)
    result = await harness.sequences.rerun(result.run_id, 2)
    record = result.record                      # a RunRecord
```

`open` is synchronous and loads the instance, its settings and its default backend; every start-up failure, an unknown person name included, raises `RunCannotStart`. The harness is an async context manager. Its namespaces:

| Namespace | What it does |
|---|---|
| `harness.nodes.run(node, inputs, backend=)` | one bounded node run, with no checkpoint; returns an `Outcome` |
| `harness.sequences.run / resume / rerun` | a sequence as one journalled run: each step is recorded by DBOS, the run record is returned; a run that raised ends `failed` and its record keeps its partial steps and facts |
| `harness.tools.register / register_server` | function tools and MCP servers of the client's own |
| `harness.events.record()` | the neutral events of the runs so far |
| `harness.extensions.register(kind, name, provider)` | a backend, context, person, resources or journal of the client's own |
| `harness.sessions` | raises `FeatureNotSupported`: sessions are step 7 |

`person` is a `Person` or the name of a registered one (`"terminal"`, `"nobody"`); `runs` is the directory of the run directories and the journal (default `<instance directory>/runs/`).

## Instances

An instance is a directory with `instance.yaml` (name, entry, policy, backend, settings, servers, function tools), `topology.yaml` (the nodes, fragments and sequences), and the policy document.

- **Nodes are files.** A node is one Markdown file with frontmatter (name, description, inputs, outputs, exits, allowed tools, preconditions) and numbered steps, named by its `path` in `topology.yaml`.
- **Includes.** Prose shared between nodes is an include: `{{include includes/safety.md}}` in a node's text, a file under the instance's `includes/`.
- **The topology** names the sequences (a start, transitions on each node's outcome, checks before the first step), the fragments (a declared unit, walked as one step, with a fan-out), and the exits.
- **Function tools** are `name: module:function` under `tools:`; MCP servers are under `servers:`; both are checked and listed to a node by name.

## Install

Python 3.12 or later. The settings library `mountainash-settings` is pinned to a revision in `pyproject.toml` until it is published.

`uv` does not apply the `[tool.uv.sources]` of agent-core to a project that depends on it. A project that depends on agent-core by path must repeat the source of `mountainash-settings` in its own `pyproject.toml`, or `uv sync` cannot resolve it:

```toml
[tool.uv.sources]
mountainash-settings = { git = "ssh://git@github.com/mountainash-io/mountainash-settings.git", rev = "7a4b43bf4789b43a808ca1520012fc413d221e64" }
```

```bash
uv sync    # the core, the test tools and the shell server
```

## `agent-core job`

`agent-core job <instance.yaml> <sequence>` runs a sequence of the topology. A name that is not a sequence exits 2, listing the sequences.

```bash
agent-core job instance.yaml lookup_then_count --input name=alpha
```

| Option | Meaning |
|---|---|
| `--settings FILE` | a settings file; repeatable; layered over the instance's own |
| `--param KEY=VALUE` | a setting; repeatable; beats the environment, which beats the files |
| `--input KEY=VALUE` | a fact the sequence starts with; repeatable |
| `--backend NAME` | the backend, instead of the instance's |
| `--no-ask` | a question ends the node run even when a person is at the terminal |
| `--run-dir DIR` | default `<instance directory>/runs/<run id>/`; a run id is `<sequence>-<UTC start>-<six hex digits>` |
| `--resume RUN_ID` | continue the run `RUN_ID`: the steps that finished are not run again |
| `--rerun-from RUN_ID:STEP` | a new run: `RUN_ID`'s steps before `STEP` are replayed from its results, the rest run with the instance as it is now |

The command opens the harness with the terminal as the person when standard input is a terminal and `--no-ask` is not given, and with nobody otherwise. It prints `run <id>` first, runs the sequence, and writes `record.json` in the run directory: the run id, its end state (`done`, `stopped` or `failed`), its steps in order, its final facts, the summary, the failures and a note for each node run of this process. The exit code is `0` when the sequence ended `done` or `stopped`, `1` when it ended `failed` or the run raised, and `2` when the run could not start (one line, `error: ...`, is printed). A job is started by whatever the host provides (cron, a systemd timer, CI); the core has no scheduler.

Each step is recorded by DBOS in `journal.sqlite` beside the run directories. A run is resumed only when `--resume` names it. Resuming a run that finished returns its result; resuming a run that raised raises its error again, and `--rerun-from` that step is the way on.

## Tests

```bash
uv run pytest -q    # the whole suite, including the shell server's tests: no model
```

Tests marked `model` do not run by default.
