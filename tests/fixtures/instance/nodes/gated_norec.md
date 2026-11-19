---
name: gated_norec
description: Do the unstamped work of the corpus. Used to test that a check which is not met records nothing.
inputs: {}
outputs:
  stamp: {type: string, description: the stamp the check left}
exits: [done, failed]
allowed-tools: []
preconditions:
  - tool: stamp_unready
    message: "The corpus {{settings.CORPUS_NAME}} is not stamped."
---
# Gated, with a check that is not met

## Steps

1. EXIT `done` with `outputs` set to an empty object.
