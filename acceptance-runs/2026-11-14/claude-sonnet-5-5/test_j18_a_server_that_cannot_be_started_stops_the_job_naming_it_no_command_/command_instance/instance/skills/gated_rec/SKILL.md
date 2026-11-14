---
name: gated_rec
description: Do the stamped work of the corpus. Used to test a check that leaves facts for the node it guards.
inputs: {}
outputs:
  stamp: {type: string, description: the stamp the check left}
exits: [done, failed]
allowed-tools: []
preconditions:
  - tool: stamp_ready
    message: "The corpus {{settings.CORPUS_NAME}} could not be stamped."
---
# Gated, with a check that records

Checked by: {{node.checked_by}}.

## Steps

1. EXIT `done` with `outputs` set to an empty object. Do not give `stamp`: the check recorded it before this node started.
