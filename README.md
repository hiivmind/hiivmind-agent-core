# agent-core

A small Python harness that runs model-driven procedures (nodes) for jobs. The core imports no agent framework.

## Acceptance

`tests/acceptance/test_job_criteria.py` runs `agent-core job --backend langgraph` on the fixture instance with a real model. It carries the marker `model`, so it does not run by default:

```bash
uv run pytest tests/acceptance -m model -q -rs     # the model is AGENT_CORE_LANGGRAPH_MODEL, default claude-sonnet-5-5
```

Its run directories (each with the provider trace `trace.jsonl` and the run record `record.json`) are kept under `acceptance-runs/<date>/<model>/<test>/`.

Results of 2026-11-14, 28 tests each:

- `claude-haiku-5-5`: first run 27 passed, 1 failed (`j3`: after the output of the wrong shape was sent back once, the model asked the person instead of correcting it; the node file `shape` now says not to). After that change, 28 passed, none skipped as "not exercised".
- `claude-sonnet-5-5` (the pass bar): 28 passed, none skipped as "not exercised". Criteria covered: 1, 3 (a) to (g), 12, 14 (job), 17 (job), 20, 21 (job), 22 (job).
