# agent-core

A small Python harness that runs model-driven procedures, called nodes, for jobs. A node is a Markdown file of numbered steps. A backend drives one bounded run of one node with a model; the core owns the state, the tools, the person and the record. The core imports no agent framework: each framework sits behind a backend, and a backend is a provider the core is handed by name.

Step 1a ships the `job` command. Sessions, `run` and `lint` are step 2's.

## Layout

- `src/agent_core/`: the core (`core/`), the contracts it and the providers share (`contracts/`), and the providers: backends (`backends/`), tool sources (`tools/`), resources, stores, persons and context strategies. The assets `ENGINE.md` and `PROCEDURES.md`, which every node run is given, are package data (`assets/`).
- `packages/agent-tools/`: a second distribution, with the shell server (`shell__run`). The core ships no tools.
- `docs/inspection-step-1a.md`: the checklist of obligations that no test shows, and the map from the review's test list to tests.

## Install

Python 3.12 or later. The settings library `mountainash-settings` is pinned to a revision in `pyproject.toml` until it is published.

```bash
uv sync                       # the core, the test tools and the shell server
uv sync --extra langgraph     # also the LangGraph backend (LangChain, LangGraph, langchain-anthropic)
```

## Run a job

An instance is a directory with `instance.yaml`, `topology.yaml`, `POLICY.md`, nodes under `skills/` and job scripts under `jobs/`. A job is the file `jobs/<name>.py` with an `async def main(job)`. It has `job.settings`, `await job.call(tool, args)` for a tool of the instance, and `await job.run_node(node, inputs)` for a node run; what `main` returns is the job's summary.

```bash
uv run agent-core job tests/fixtures/instance/instance.yaml nothing --param CORPUS_REPO=/tmp
```

| Option | Meaning |
|---|---|
| `--settings FILE` | a settings file; repeatable; layered over the instance's own |
| `--param KEY=VALUE` | a setting; repeatable; beats the environment, which beats the files |
| `--backend NAME` | the backend, instead of the instance's |
| `--no-ask` | a question ends the node run even when a person is at the terminal |
| `--run-dir DIR` | default `<instance directory>/runs/<job>-<UTC start>/` |

The run directory holds `record.json`: what the job did, the status, the summary, the node runs and their cost. The exit code is `0` when the job succeeded, `1` when it failed and `2` when the run could not start (a message of one line is printed). A job is started by whatever the host provides (cron, a systemd timer, CI); the core has no scheduler.

## How a backend is chosen

For a node run: the `backend` argument of `job.run_node`, else `--backend`, else `backend:` in `instance.yaml`. An unknown name, or a backend whose package is not installed, stops the run before it starts (exit code 2) and lists the backends that exist. There are two:

- `langgraph`: a real model through LangChain. It needs the `langgraph` extra and `ANTHROPIC_API_KEY`. Its settings come from the environment with the prefix `AGENT_CORE_LANGGRAPH_` (`MODEL`, default `claude-sonnet-5-5`; `MAX_TOKENS`; `RECURSION_LIMIT`).
- `scripted`: answers from JSON scripts, one file for each node, in the directory named by `AGENT_CORE_SCRIPTED_SCRIPTS`. It calls no model; the tests use it.

An instance may register providers of its own (`providers:` in `instance.yaml` lists the files; `sources:` names a tool source by its registered name).

## Tests

```bash
uv run pytest -q                              # the default suite, including the shell server's tests: no model
uv run pytest tests/conformance -m model -q   # a backend against the contract: calls a model, costs money
uv run pytest tests/acceptance -m model -q -rs  # the job criteria through the command: calls a model, costs money
```

Tests marked `model` do not run by default. The two model suites use the model in `AGENT_CORE_LANGGRAPH_MODEL`: develop on `claude-haiku-5-5`; the pass bar is one pass on `claude-sonnet-5-5`. They need `ANTHROPIC_API_KEY` and the `langgraph` extra.

## Specifications

The requirements and the architecture the code follows are in the `hiivmind-central` repository, under its planning folder:

- Requirements: `04.planning/hiivmind-agent-core/superpowers/specs/2026-11-11-agent-core-design.md`
- Architecture design: `04.planning/hiivmind-agent-core/superpowers/specs/2026-11-14-agent-core-architecture-design.md`

`docs/inspection-step-1a.md` answers the requirements that no test shows.

## Acceptance

`tests/acceptance/test_job_criteria.py` runs `agent-core job --backend langgraph` on the fixture instance with a real model. It carries the marker `model`, so it does not run by default:

```bash
uv run pytest tests/acceptance -m model -q -rs     # the model is AGENT_CORE_LANGGRAPH_MODEL, default claude-sonnet-5-5
```

Its run directories (each with the provider trace `trace.jsonl` and the run record `record.json`) are kept under `acceptance-runs/<date>/<model>/<test>/`.

Results of 2026-11-14, 28 tests each:

- `claude-haiku-5-5`: first run 27 passed, 1 failed (`j3`: after the output of the wrong shape was sent back once, the model asked the person instead of correcting it; the node file `shape` now says not to). After that change, 28 passed, none skipped as "not exercised".
- `claude-sonnet-5-5` (the pass bar): 28 passed, none skipped as "not exercised". Criteria covered: 1, 3 (a) to (g), 12, 14 (job), 17 (job), 20, 21 (job), 22 (job).
