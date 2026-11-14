---
name: gated_missing
description: Do the work behind a check that cannot be run. Used to test a precondition whose tool the instance does not declare.
inputs: {}
outputs:
  done_work: {type: string, description: what was done}
exits: [done, failed]
allowed-tools: [tools__shell]
preconditions:
  - tool: nosuchtool
    args: {command: "true"}
    message: "This message must never be shown: the check cannot be run."
---
# Gated by a missing tool

## Steps

1. CALL `tools__shell` with the command `echo gated-missing-work`.
2. EXIT `done` with output `done_work` set to `gated-missing-work`.
