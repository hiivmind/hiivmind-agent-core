---
name: gated_route
description: Do the work of a v2 corpus. Used to test a precondition that names the outcome it gives.
inputs: {}
outputs:
  done_work: {type: string, description: what was done}
exits: [done, v1, failed]
allowed-tools: []
preconditions:
  - tool: never_ready
    outcome: v1
    message: "The corpus {{settings.CORPUS_NAME}} has a v1 index."
---
# Gated by a routing check

## Steps

1. EXIT `done` with output `done_work` set to `v2-work`.
