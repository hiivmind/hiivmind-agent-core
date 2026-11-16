---
name: graph
description: Toy graph node for testing sequences.
inputs:
  action: what to do with the graph
outputs:
  result:
    type: string
    description: result
exits:
- done
- failed
allowed-tools: []
preconditions:
- tool: log_input
  args:
    action: '{{input.action}}'
  message: never unmet
---
# graph

## Steps

1. EXIT with the outcome and outputs the script gives.
