---
name: badshape
description: Exit with a total of the wrong kind.
inputs: {}
outputs:
  total: {type: integer, description: a whole number}
exits: [done, failed]
allowed-tools: []
---
# Badshape

## Steps

1. EXIT `done` with output `total` set to the text `three` (a string, exactly that text), whatever the schema says.
2. If the exit is refused, correct the output as the refusal asks and EXIT again.
