---
name: ask
description: Ask the person which colour to use.
inputs: {}
outputs:
  colour: {type: string, description: the colour the person chose}
exits: [done, failed]
allowed-tools: []
---
# Ask

## Steps

1. ASK exactly: "Which colour?"
2. EXIT `done` with output `colour` set to the answer.
