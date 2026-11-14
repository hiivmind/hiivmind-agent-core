---
name: gated_fn
description: Do the function-gated work of the corpus. Used to test a precondition the harness checks with a plain function.
inputs: {}
outputs:
  done_work: {type: string, description: what was done}
exits: [done, failed]
allowed-tools: [tools__shell]
preconditions:
  - tool: never_ready
    message: "The corpus {{settings.CORPUS_NAME}} is never ready for this."
---
# Gated by a function

## Steps

1. CALL `tools__shell` with the command `echo gated-fn-work`.
2. EXIT `done` with output `done_work` set to `gated-fn-work`.
