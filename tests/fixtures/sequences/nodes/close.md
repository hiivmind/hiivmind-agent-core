---
name: close
description: Close the work. The second node of the tail fragment.
inputs: {}
outputs:
  closed: {type: string, description: what was closed}
exits: [done, failed]
allowed-tools: []
---
# Close

## Steps

1. EXIT `done` with output `closed` set to `yes`.
