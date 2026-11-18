---
name: status
description: Toy status node for testing sequences.
inputs: {}
outputs:
  refresh_needed:
    type: boolean
    description: refresh_needed
exits:
- stale
- current
- failed
allowed-tools: []
---
# status

## Steps

1. EXIT with the outcome and outputs the script gives.
