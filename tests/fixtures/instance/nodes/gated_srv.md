---
name: gated_srv
description: Do the marked work of the corpus. Used to test a precondition checked by a server's tool that is not the shell.
inputs: {}
outputs:
  done_work: {type: string, description: what was done}
exits: [done, failed]
allowed-tools: [tools__shell]
preconditions:
  - tool: tools__ready
    args: {name: "{{settings.CORPUS_NAME}}"}
    message: "The corpus {{settings.CORPUS_NAME}} is not marked ready."
---
# Gated by a server's tool

## Steps

1. CALL `tools__shell` with the command `echo gated-srv-work`.
2. EXIT `done` with output `done_work` set to `gated-srv-work`.
