---
name: asker
description: Ask which colour a source gets. Used to test questions from nodes that run at the same time.
inputs:
  who: the source the colour is for
outputs:
  colour: {type: string, description: the colour the user chose}
exits: [done, failed]
allowed-tools: []
---
# Asker

## Steps

1. ASK exactly: "Which colour for {{input.who}}?"
2. EXIT `done` with output `colour` set to the user's answer, word for word.
