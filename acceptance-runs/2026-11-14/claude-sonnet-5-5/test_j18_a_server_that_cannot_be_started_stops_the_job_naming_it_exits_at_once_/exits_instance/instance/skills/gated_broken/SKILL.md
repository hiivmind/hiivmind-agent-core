---
name: gated_broken
description: Do the work behind a check function that raises. Used to test a precondition function that fails to run.
inputs: {}
outputs:
  done_work: {type: string, description: what was done}
exits: [done, failed]
allowed-tools: [tools__shell]
preconditions:
  - tool: broken_check
    message: "This message must never be shown: the check cannot be run."
---
# Gated by a broken function

## Steps

1. CALL `tools__shell` with the command `echo gated-broken-work`.
2. EXIT `done` with output `done_work` set to `gated-broken-work`.
