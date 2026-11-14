---
name: gated
description: Do the gated work of the corpus. Used to test a precondition the harness checks before the node starts.
inputs: {}
outputs:
  done_work: {type: string, description: what was done}
exits: [done, failed]
allowed-tools: [tools__shell]
preconditions:
  - tool: tools__shell
    args: {command: "test -f {{settings.CORPUS_NAME}}.ready"}
    message: "The corpus {{settings.CORPUS_NAME}} is not ready: there is no {{settings.CORPUS_NAME}}.ready file."
---
# Gated

## Steps

1. CALL `tools__shell` with the command `echo gated-work`.
2. EXIT `done` with output `done_work` set to `gated-work`.
