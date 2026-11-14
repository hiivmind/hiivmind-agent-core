---
name: ledger
description: Read the main ledger of the corpus. Used to test a function tool that raises.
inputs: {}
outputs:
  entries: {type: integer, description: how many entries the ledger has}
exits: [done, failed]
allowed-tools: [read_ledger]
---
# Ledger

## Steps

1. CALL `read_ledger` with `name` set to `main`.
2. If the call returned an error, EXIT `failed` with `reason` set to the error. Do not try again.
3. Otherwise EXIT `done` with output `entries` set to the number of entries.
