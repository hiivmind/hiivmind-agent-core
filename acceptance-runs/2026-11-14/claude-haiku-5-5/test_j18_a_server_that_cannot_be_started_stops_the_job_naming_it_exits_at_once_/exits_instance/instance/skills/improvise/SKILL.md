---
name: improvise
description: Answer a question or small request that no other node serves.
inputs:
  request: what the user asked
outputs: {}
exits: [done]
allowed-tools: []
---
# Improvise

The user's request: {{input.request}}.

## Steps

1. In one response, answer the request in one or two sentences of plain text and EXIT `done` with no outputs.
