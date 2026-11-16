---
name: publish
description: Toy publish node for testing sequences.
inputs:
  sources_updated: what changed
  entries: entries changed
outputs:
  pr_url:
    type: string
    description: pr_url
exits:
- published
- nothing-to-publish
- failed
allowed-tools:
- crash_point
---
# publish

## Steps

1. EXIT with the outcome and outputs the script gives.
