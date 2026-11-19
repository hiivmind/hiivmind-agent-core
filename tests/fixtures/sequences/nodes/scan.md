---
name: scan
description: Toy scan node for testing sequences.
inputs:
  batch: one batch of files
outputs:
  entries:
    type: array
    description: entries
exits:
- done
- failed
allowed-tools:
- crash_point
---
# scan

## Steps

1. EXIT with the outcome and outputs the script gives.
