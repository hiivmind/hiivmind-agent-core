---
name: guarded
description: Do the guarded work of the corpus. Used to test a precondition that is not met.
inputs: {}
outputs:
  done_work: {type: string, description: what was done}
exits: [done, failed]
allowed-tools: [tools__shell]
---
# Guarded

## Steps

1. Precondition: a file named `config.yaml` exists in the working directory. Check it by CALLing `tools__shell` with the command `test -f config.yaml && echo present || echo missing`. If it is missing, EXIT `failed` with a `reason` that says so, and do nothing else.
2. CALL `tools__shell` with the command `echo guarded-work`.
3. EXIT `done` with output `done_work` set to `guarded-work`.
