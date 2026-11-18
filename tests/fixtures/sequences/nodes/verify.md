---
name: verify
description: Toy verify node for testing sequences.
inputs:
  entries: entries to check
outputs:
  drift:
    type: integer
    description: drift
exits:
- done
- failed
allowed-tools:
- crash_point
---
# verify

## Steps

1. EXIT with the outcome and outputs the script gives.
