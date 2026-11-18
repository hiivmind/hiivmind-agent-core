# agent-core

A small Python harness that runs model-driven procedures, called nodes, for jobs. A node is a Markdown file of numbered steps. A backend drives one bounded run of one node with a model; the core owns the state, the tools, the person and the record. The core imports no agent framework: each framework sits behind a backend, and a backend is a provider the core is handed by name.

Step 1a ships the `job` command; step 1c adds sequence jobs. Sessions, `run` and `lint` are step 2's.

## Layout

- `src/agent_core/`: the core (`core/`), the contracts it and the providers share (`contracts/`), and the providers: backends (`backends/`), tool sources (`tools/`), resources, stores, persons, context strategies and run journals (`journals/`). The assets `ENGINE.md` and `PROCEDURES.md`, which every node run is given, are package data (`assets/`).
- `packages/agent-tools/`: a second distribution, with the shell server (`shell__run`). The core ships no tools.
- `docs/inspection-step-1a.md`: the checklist of obligations that no test shows, and the map from the review's test list to tests.

## Install

Python 3.12 or later. The settings library `mountainash-settings` is pinned to a revision in `pyproject.toml` until it is published.

`uv` does not apply the `[tool.uv.sources]` of agent-core to a project that depends on it. A project that depends on agent-core by path must repeat the source of `mountainash-settings` in its own `pyproject.toml`, or `uv sync` cannot resolve it:

```toml
[tool.uv.sources]
mountainash-settings = { git = "ssh://git@github.com/mountainash-io/mountainash-settings.git", rev = "7a4b43bf4789b43a808ca1520012fc413d221e64" }
```

```bash
uv sync                       # the core, the test tools and the shell server
uv sync --extra langgraph     # also the LangGraph backend (LangChain, LangGraph, langchain-anthropic)
```

## Run a job

An instance is a directory with `instance.yaml`, `topology.yaml`, `POLICY.md`, nodes under `skills/` and job scripts under `jobs/`. `agent-core job <instance.yaml> <name>` runs the sequence `<name>` of the topology, or else the job script `jobs/<name>.py`; a name that is both stops the run. A job script has an `async def main(job)`. It has `job.settings`, `await job.call(tool, args)` for a tool of the instance, and `await job.run_node(node, inputs)` for a node run; what `main` returns is the job's summary.

```bash
uv run agent-core job tests/fixtures/instance/instance.yaml nothing --param CORPUS_REPO=/tmp
```

| Option | Meaning |
|---|---|
| `--settings FILE` | a settings file; repeatable; layered over the instance's own |
| `--param KEY=VALUE` | a setting; repeatable; beats the environment, which beats the files |
| `--backend NAME` | the backend, instead of the instance's |
| `--no-ask` | a question ends the node run even when a person is at the terminal |
| `--run-dir DIR` | default `<instance directory>/runs/<run id>/`; a run id is `<name>-<UTC start>-<six hex digits>` |
| `--input KEY=VALUE` | a fact a sequence starts with; repeatable |
| `--resume RUN_ID` | continue the sequence run `RUN_ID`: the steps that finished are not run again |
| `--rerun-from RUN_ID:STEP` | a new sequence run: `RUN_ID`'s steps before `STEP` are replayed from its results, the rest run with the instance as it is now |

`--input`, `--resume` and `--rerun-from` apply to sequences; a job script ignores them. A resume or a re-run is given the same name and settings as the run it continues.

The run directory holds `record.json`: what the job did, the status, the summary, the node runs of this process and their cost. A sequence's record also has its run id, its end state (`done`, `stopped` or `failed`), its steps in order and its final facts. The exit code is `0` when the job succeeded or the sequence ended `done` or `stopped`, `1` when it failed or the run raised, and `2` when the run could not start (a message of one line is printed). A job is started by whatever the host provides (cron, a systemd timer, CI); the core has no scheduler.

A sequence run prints its run id first. Each of its steps is recorded by DBOS in `journal.sqlite` beside the run directories (`<instance directory>/runs/journal.sqlite` by default). A run is resumed only when `--resume` names it. Resuming a run that finished returns its result; resuming a run that raised raises its error again, and `--rerun-from` that step is the way on.

## How a backend is chosen

For a node run: the `backend` argument of `job.run_node`, else `--backend`, else `backend:` in `instance.yaml`. An unknown name, or a backend whose package is not installed, stops the run before it starts (exit code 2) and lists the backends that exist. There are two:

- `langgraph`: a real model through LangChain. It needs the `langgraph` extra and `ANTHROPIC_API_KEY`. Its settings come from the environment with the prefix `AGENT_CORE_LANGGRAPH_` (`MODEL`, default `claude-sonnet-5-5`; `MAX_TOKENS`, default 16000, the limit on the tokens of one model reply, so `AGENT_CORE_LANGGRAPH_MAX_TOKENS=32000` raises it; `RECURSION_LIMIT`).
- `scripted`: answers from JSON scripts, one file for each node, in the directory named by `AGENT_CORE_SCRIPTED_SCRIPTS`. It calls no model; the tests use it.

An instance may register providers of its own (`providers:` in `instance.yaml` lists the files; `sources:` names a tool source by its registered name).

## Tests

```bash
uv run pytest -q                              # the default suite, including the shell server's tests: no model
uv run pytest tests/conformance -m model -q   # a backend against the contract: calls a model, costs money
uv run pytest tests/acceptance -m model -q -rs  # the job criteria through the command: calls a model, costs money
```

Tests marked `model` do not run by default. The two model suites use the model in `AGENT_CORE_LANGGRAPH_MODEL`: develop on `claude-haiku-5-5`; the pass bar is one pass on `claude-sonnet-5-5`. They need `ANTHROPIC_API_KEY` and the `langgraph` extra.

### Acceptance runs

The acceptance suite, `tests/acceptance/test_job_criteria.py`, runs `agent-core job --backend langgraph` on the fixture instance with a real model. It carries the marker `model`, so it does not run by default (command above). Its run directories (each with the provider trace `trace.jsonl` and the run record `record.json`) are written to `acceptance-runs/<date>/<model>/<test>/` and are not committed.

Results, all of 2026-11-14:

| Date | Model | Suite | Result |
|---|---|---|---|
| 2026-11-14 | `claude-haiku-5-5` | acceptance, first run | 27 of 28 passed (`j3` failed) |
| 2026-11-14 | `claude-haiku-5-5` | acceptance, after the `shape` node change | 28 of 28 passed |
| 2026-11-14 | `claude-sonnet-5-5` | acceptance, before the `ENGINE.md` change | 28 of 28 passed |
| 2026-11-14 | `claude-haiku-5-5` | conformance, after the final review's fixes | 11 of 11 passed |
| 2026-11-14 | `claude-haiku-5-5` | acceptance, after the final review's fixes | 28 of 28 passed |

Details, 28 tests each:

- `claude-haiku-5-5`: first run 27 passed, 1 failed (`j3`: after the output of the wrong shape was sent back once, the model asked the person instead of correcting it; the node file `shape` now says not to). After that change, 28 passed, none skipped as "not exercised".
- `claude-sonnet-5-5` (the pass bar): 28 passed, none skipped as "not exercised". Criteria covered: 1, 3 (a) to (g), 12, 14 (job), 17 (job), 20, 21 (job), 22 (job).

Re-run after the final review's fixes (the documents `ENGINE.md` and `PROCEDURES.md` had changed since the runs above), each once on `claude-haiku-5-5`, one after the other:

- `tests/conformance -m model`: 11 passed, none skipped.
- `tests/acceptance -m model`: 28 passed, none skipped.

## Specifications

The requirements and the architecture the code follows are in the `hiivmind-central` repository, under its planning folder:

- Requirements: `04.planning/hiivmind-agent-core/superpowers/specs/2026-11-11-agent-core-design.md`
- Architecture design: `04.planning/hiivmind-agent-core/superpowers/specs/2026-11-14-agent-core-architecture-design.md`

`docs/inspection-step-1a.md` answers the requirements that no test shows.

## Rebuild in progress

The rebuild is in progress on the branch `rebuild`. The old tree (v0) is under `v0/` and at the tag `v0-final`; the paragraphs above describe v0 until the cutover replaces them.
