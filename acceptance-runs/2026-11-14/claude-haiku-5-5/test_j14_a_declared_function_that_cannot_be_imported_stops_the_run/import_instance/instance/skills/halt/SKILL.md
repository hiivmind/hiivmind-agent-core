---
name: halt
description: Report a code. Used to see what the model does when no output can satisfy the schema and it is not told to persist.
inputs: {}
outputs:
  code: {type: integer, minimum: 10, maximum: 5, description: the code}
exits: [done]
allowed-tools: []
---
# Halt

## Steps

1. EXIT `done` with output `code` set to 7.
