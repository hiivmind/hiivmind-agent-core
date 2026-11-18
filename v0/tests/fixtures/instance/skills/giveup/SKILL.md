---
name: giveup
description: Report a code. Used to test a node's own failed exit; its output schema cannot be satisfied by any value.
inputs: {}
outputs:
  code: {type: integer, minimum: 10, maximum: 5, description: the code}
exits: [done, failed]
allowed-tools: []
---
# Give up

## Steps

1. EXIT `done` with output `code` set to 7.
2. If the outputs are rejected, EXIT `failed` and say why in a short `reason`.
