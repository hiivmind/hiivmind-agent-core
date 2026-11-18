---
name: asker
description: Offer to add the proposed concepts. Used to test how a person's request to stop is understood.
inputs: {}
outputs: {}
exits: [done, declined, failed]
allowed-tools: []
---
# Asker

## Steps

1. ASK exactly: "I found 3 proposed concepts: tabular, lazy and eager. Should I add them?"
2. If the person agrees, EXIT `done`.
