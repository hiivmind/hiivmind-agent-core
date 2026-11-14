---
name: stuck
description: Report a code. Used to test the output check; its output schema cannot be satisfied by any value.
inputs: {}
outputs:
  code: {type: integer, minimum: 10, maximum: 5, description: the code}
exits: [done]
allowed-tools: []
---
# Stuck

## Steps

1. EXIT `done` with output `code` set to 7.
2. If the outputs are rejected, EXIT `done` again with output `code` set to 8. Always finish by calling EXIT; never reply with text only.
