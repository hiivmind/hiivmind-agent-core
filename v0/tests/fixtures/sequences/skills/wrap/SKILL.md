---
name: wrap
description: Finish the work. Used as the step after asker.
inputs: {}
outputs:
  wrapped: {type: string, description: what was finished}
exits: [done, failed]
allowed-tools: []
---
# Wrap

## Steps

1. EXIT `done` with output `wrapped` set to `yes`.
