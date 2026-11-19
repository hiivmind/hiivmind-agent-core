---
name: choose
description: Use the colour given, or ask for one.
inputs:
  colour: the colour to use
outputs:
  colour: {type: string, description: the colour used}
exits: [done, failed]
allowed-tools: []
---
# Choose

Colour given: {{input.colour}}.

## Steps

1. If a colour was given above, go to step 3. If it says "not given", ASK exactly: "Which colour?"
2. STATE.set `colour` to the answer.
3. EXIT `done` with output `colour` set to the colour.
