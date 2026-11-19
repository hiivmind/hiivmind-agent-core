---
name: guarded
description: Look a name up only when the register may be used for it.
inputs:
  name: the name to look up
outputs:
  revision: {type: string, description: the revision of the name}
exits: [done, failed]
allowed-tools: [lookup_revision]
---
# Guarded

Name to look up: {{input.name}}.

## Steps

1. Check the precondition: the name must be one of `alpha`, `beta`, `gamma`. If it is not, EXIT `failed` with output `reason` set to `name not in the register`, and do nothing more.
2. CALL `lookup_revision`.
3. EXIT `done` with output `revision`.
