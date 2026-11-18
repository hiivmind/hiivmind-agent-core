---
name: update-sources
description: Toy update-sources node for testing sequences.
inputs: {}
outputs:
  rescan_batches:
    type: array
    description: rescan_batches
  sources_updated:
    type: array
    description: sources_updated
exits:
- updated
- current
- failed
allowed-tools: []
---
# update-sources

## Steps

1. EXIT with the outcome and outputs the script gives.
