---
name: index
description: Toy index node for testing sequences.
inputs:
  scans: the scan results
outputs:
  entries:
    type: array
    description: entries
exits:
- done
- declined
- failed
allowed-tools: []
---
# index

## Steps

1. EXIT with the outcome and outputs the script gives.
