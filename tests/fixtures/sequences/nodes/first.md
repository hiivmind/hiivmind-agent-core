---
name: first
description: Do the first work. Its done leads to the tail fragment.
inputs: {}
outputs:
  first_done: {type: string, description: what was done first}
exits: [done, failed]
allowed-tools: []
---
# First

## Steps

1. EXIT `done` with output `first_done` set to `yes`.
