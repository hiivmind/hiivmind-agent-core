---
name: consult
description: Look a key up in the corpus register. Used to test a tool server's own error.
inputs: {}
outputs:
  value: {type: string, description: the value found}
exits: [done, failed]
allowed-tools: [tools__lookup]
---
# Consult

## Steps

1. CALL `tools__lookup` with `key` set to `missing`.
2. If the call returned an error, EXIT `failed` with `reason` set to the error. Do not try again.
3. Otherwise EXIT `done` with output `value` set to the value found.
