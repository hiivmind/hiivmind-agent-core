---
name: locate_quiet
description: Record where a source of the corpus is kept, without saying it again. Used to test an output that code records.
inputs:
  source: the source to locate
outputs:
  path: {type: string, description: where the source is kept}
exits: [done, failed]
allowed-tools: [locate]
---
# Locate quietly

Source to locate: {{input.source}}.

## Steps

1. CALL `locate` with `source` set to the source above. The tool records the output `path` itself.
2. EXIT `done` with `outputs` set to an empty object. Do not give `path` again: the harness already holds it.
