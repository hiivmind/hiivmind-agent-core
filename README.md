# agent-core

A small Python harness that runs model-driven procedures, called nodes, and walks them as sequences, either as a job with nobody at the terminal or in a session with the person there. `agent_core.open(instance)` returns one runtime object; `agent-core job` and `agent-core run` are clients of it. The core imports no agent framework: each framework sits behind a backend, which is a provider the core is handed by name.

The old tree (v0) is kept at the tag `v0-final`; it is not in this tree.

The design documents (architecture, requirements and the layered facade design, 2026-11-18) are kept in the maintainers' private planning repository; this README and the code are the public record.

## Layers

`src/agent_core/`, each layer importing only the ones named (`tests/layering` checks this by AST):

| Directory | Holds | Imports |
|---|---|---|
| `contracts/` | the protocols and values every layer shares: `Backend`, `Policy`, the topology, the facade's protocols, the events, the matrix of features | nothing of ours, no SDK |
| `core/` | the facade, core policy (one `NodePolicy` per node run), the macro walk's driver, the session and its routing run, the instance loader, the registry | `contracts/` |
| `helpers/` | the walk (a sequence or a fragment, fan-out), the MCP client | `contracts/` |
| `backends/`, `journals/`, `person/`, `resources/`, `context/`, `stores/` | providers: the scripted backend, the DBOS journal, the terminal and nobody, the folder, the `none`, `all` and `summary` strategies, the file store | `contracts/`, `helpers/` |
| `cli.py` | `agent-core job` and `agent-core run` | `agent_core` (its public `open`) only |

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
    session = await harness.sessions.start()    # a SessionResult: `ended`, or `waiting` for a person who has gone
    session = await harness.sessions.resume(session.session_id)
```

`open` is synchronous and loads the instance, its settings and its default backend; every start-up failure, an unknown person name included, raises `RunCannotStart`. The harness is an async context manager. Its namespaces:

| Namespace | What it does |
|---|---|
| `harness.nodes.run(node, inputs, backend=)` | one bounded node run, with no checkpoint; returns an `Outcome` |
| `harness.sequences.run / resume / rerun` | a sequence as one journalled run: each step is recorded by DBOS, the run record is returned; a run that raised ends `failed` and its record keeps its partial steps and facts |
| `harness.tools.register / register_server` | function tools and MCP servers of the client's own |
| `harness.events.record()` | the neutral events of the runs so far |
| `harness.extensions.register(kind, name, provider)` | a backend, context, person, resources, journal or store of the client's own |
| `harness.sessions.start(name=None) / resume(session_id)` | a session with the harness's person: entered at a node or a sequence, or opened with the topology's greeting and menu; it ends on an outcome whose exit handling is `end`, or returns `waiting` when the person has gone, saved to be resumed; raises `FeatureNotSupported` where the default backend builds no sessions (F6, F17) |

`person` is a `Person` or the name of a registered one (`"terminal"`, `"nobody"`); its `ask` takes a `Question` (the text, the node, its run number and its inputs). `runs` is the directory of the run directories and the journal (default `<instance directory>/runs/`).

## Instances

An instance is a directory with `instance.yaml` (name, entry, policy, backend, settings, servers, function tools), `topology.yaml` (the nodes, fragments and sequences), and the policy document.

- **Nodes are files.** A node is one Markdown file with frontmatter (name, description, inputs, outputs, exits, allowed tools, preconditions) and numbered steps, named by its `path` in `topology.yaml`.
- **Includes.** Prose shared between nodes is an include: `{{include includes/safety.md}}` in a node's text, a file under the instance's `includes/`.
- **The topology** names the sequences (a start, transitions on each node's outcome, checks before the first step), the fragments (a declared unit, walked as one step, with a fan-out), and the exits.
- **Function tools** are `name: module:function` under `tools:`; MCP servers are under `servers:`; both are checked and listed to a node by name.
- **An instance's files import each other relatively** (`from .sources import X`): the instance directory is loaded as a package of its own, and nothing is put on `sys.path`.
- **The run's variables reach servers only.** A server starts with `AGENT_CORE_INSTANCE` and `AGENT_CORE_RUN_DIR` in its environment; a function tool or a check runs in the harness's process and reads no `AGENT_CORE_*` variable, since a run does not change `os.environ`.

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

## Models and credentials (LangGraph backend)

`AGENT_CORE_LANGGRAPH_MODEL` is `provider:model` (`anthropic:claude-sonnet-5-5`, `openai:gpt-6-luna`); there is no default. Each provider needs its extra: `agent-core[langgraph,anthropic]` or `agent-core[langgraph,openai]`.

`AGENT_CORE_LANGGRAPH_CREDENTIAL` says how the provider's code obtains its credential:

| Value | Meaning |
|---|---|
| `env` (default) | the provider's key from the environment (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`) |
| `account` | OpenAI only: the ChatGPT plan of the account signed in with [`mountainash-auth-openai`](https://github.com/mountainash-io/mountainash-auth-openai), for the application `hiivmind-agent-core` |

Sign in once, in a browser; the token is refreshed without a person after that:

```bash
uv run mountainash-auth-openai sign-in --application hiivmind-agent-core
uv run mountainash-auth-openai status --application hiivmind-agent-core
AGENT_CORE_LANGGRAPH_MODEL=openai:gpt-6-luna AGENT_CORE_LANGGRAPH_CREDENTIAL=account agent-core job instance.yaml <sequence>
```

With `account`, the client is the subscription route's: the Responses API, streamed, not stored, with no output-token cap (`MAX_TOKENS` does not apply) and no temperature. Each call takes the route's shape: the node's instructions go as the request's `instructions`, since the route refuses a system message, and the tools go with `strict: false`, since the route otherwise makes the model fill every optional parameter. The core never handles a credential. Whether a use is within the "Sign in with ChatGPT" terms is the user's responsibility.

| When | What the run says |
|---|---|
| nobody is signed in, the plan permission was not given, or OpenAI refused the sign-in for good | the node fails with the sign-in package's message, naming the account and `mountainash-auth-openai sign-in --application hiivmind-agent-core`; it is not run again |
| `account` with `MODEL=anthropic:…` | the node fails: `the provider anthropic has no signed-in account; set AGENT_CORE_LANGGRAPH_CREDENTIAL=env to use its key.` |
| `account` without `mountainash-auth-openai` installed | the run does not start: ``CREDENTIAL=account needs mountainash-auth-openai: install agent-core with the extra `openai`.`` |
| the plan's usage is spent, or ChatGPT does not authorize the request | the node fails with the reason (`ChatGPT plan usage is limited. Review https://chatgpt.com/settings/usage before resuming.`); a fan-out does not run that item again |
| a refresh fails for now, or a rate limit with no usage code | retried, as any refusal that passes |

The `openai` extra takes `mountainash-auth-openai` and `mountainash-auth-client` by git revision; a project that depends on agent-core with that extra repeats them as `agent-core` does (`[tool.uv.sources]` for `mountainash-auth-openai`, `[tool.uv] override-dependencies` for its two siblings).

### Live runs on the ChatGPT plan

2026-11-21, `openai:gpt-6-luna`, `CREDENTIAL=account`, the account `069a3ecb…` signed in for `hiivmind-agent-core` with plan usage enabled.

- **The model tests** (`uv run pytest tests/model -m model`): 7 passed, 5 skipped (the wire tests read Anthropic's transport), 1 failed. The one that fails is `test_a_precondition_written_in_the_procedure_that_is_unmet_fails_the_node`: luna mostly calls `lookup_revision` before it exits `failed`, against "do nothing more" (2 passes in 11 runs; 0 in 6 with the instructions as a `developer` message, so the way they are sent is not the cause). Recorded as luna's result (owner, 2026-11-21). The same tests on `anthropic:claude-haiku-5-5` with its key: 13 passed.
- **A corpus job** (hiivmind-corpus-agent, `status` on a scratch clone of the Polars corpus, `PUSH=false`, `--no-ask`; the `openai` extra installed into its environment by hand, as its own dependency takes `agent-core[langgraph,anthropic]`): run `status-20261120T214748Z-c2dc7b` ended `done`, exit 0, with 4 model calls. Step `status` → `stale`: source `polars` `behind`, `stale_count` 37, `refresh_needed` true. The clone was unchanged.
- **Two route facts were found by these runs** and are in `ROUTE` of `mountainash-auth-openai`: a system message is refused (`400 System messages are not allowed`), and a tool sent without `strict` is strict, so the model filled both `head` and `tail` of the filesystem server's `read_text_file` and the server refused the call.
- **Not yet run: a job a day later with no sign-in in between**, showing the token refreshed without a person (deferred by the owner, 2026-11-21). The access token held at 2026-11-20T23:51Z expires at 2026-11-21T00:51:43Z, so a run after that must refresh it.

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

## `agent-core run`

`agent-core run <instance.yaml> [NAME]` opens a session at the terminal. With `NAME`, a node or a sequence, the session starts there; a name that is both is the sequence, and a name that is neither exits 2, listing both. With none, it tells the topology's `greeting` and shows its `menu`, where they exist, and hears the person.

```bash
agent-core run instance.yaml update-sources
agent-core run instance.yaml --resume session-20261125T102000Z-d4e5f6
```

| Option | Meaning |
|---|---|
| `--settings FILE`, `--param KEY=VALUE`, `--backend NAME` | as for `agent-core job` |
| `--resume SESSION_ID` | carry the session on where it stopped |

- **The loop.** A reply that is a menu item, by its number or its label in any case, enters that item by code. Any other reply goes to the routing run: a model run whose one tool is `enter`, handed the conversation so far, with the nodes (and their inputs) and the sequences listed, and the instance's `GATEWAY.md` where there is one. When what it started ends, the topology's `exits` say whether the session goes back to the person (`route`, and any outcome with no row) or ends (`end`).
- **In a node.** What the model says is shown as it says it, and when it stops without a call the person's reply goes back to it. A node is not offered `enter`: a request outside it is declined, and its question asked again. Its `context` line (`none`, `all` or `summary`) says what it is handed of the conversation so far.
- **Leaving and resuming.** End of input (Ctrl-D) at any prompt saves the session and prints how to resume it. A stopped process (Ctrl-C, a kill) loses nothing either, since each change is saved as it is made. A session is kept in `<runs>/<session id>/`: `session.json`, the node runs' checkpoints, and `record.json`, the record of the last process's part. On resume a question that was waiting is asked again; on LangGraph the node carries on from its checkpoint, on the scripted backend it runs again from its start. A session that ended is not resumed.
- **A tool server that cannot be reached** is told to the person, and their reply makes the call again.
- **Improvisation** (diversions to a temporary node) is not built yet: a topology that turns it on is refused when a session starts.

The exit code is `0` when the session ended or is saved and waiting, `1` when it raised or its record could not be written, and `2` when it could not start.

## Tests

```bash
uv run pytest -q    # the whole suite, including the shell server's tests: no model
```

Tests marked `model` do not run by default.
