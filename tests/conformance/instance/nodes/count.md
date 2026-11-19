---
name: count
description: Count what was found, with a shell command.
inputs:
  revisions: what was found
outputs:
  total: {type: integer, description: how many were found}
exits: [done, failed]
allowed-tools: [shell__run, crash_once]
---
# Count

## Steps

1. CALL `shell__run` to count.
2. EXIT `done` with output `total`.
