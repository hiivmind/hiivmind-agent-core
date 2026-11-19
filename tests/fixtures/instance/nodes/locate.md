---
name: locate
description: Say where a source of the corpus is kept. Used to test parameters that the harness fills for a function tool.
inputs:
  source: the source to locate
outputs:
  path: {type: string, description: where the source is kept}
exits: [done, failed]
allowed-tools: [locate]
---
# Locate

Source to locate: {{input.source}}.

## Steps

1. STATE.set `phase` to `looking`.
2. CALL `locate` with `source` set to the source above.
3. EXIT `done` with output `path` set to the path the tool returned.
