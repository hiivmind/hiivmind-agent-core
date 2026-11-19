---
name: sweep
description: Look up five names, one call at a time.
inputs: {}
outputs: {}
exits: [done, failed]
allowed-tools: [lookup_revision]
---
# Sweep

## Steps

1. CALL `lookup_revision` with the name `alpha`, alone in its response. Wait for its result.
2. Do the same for `beta`, then `gamma`, then `delta`, then `epsilon`: one call in each response, each after the result of the one before.
3. When the fifth result is in, EXIT `done`.
