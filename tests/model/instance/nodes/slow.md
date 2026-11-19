---
name: slow
description: Look up one name with the slow tool.
inputs: {}
outputs: {}
exits: [done, failed]
allowed-tools: [slow_lookup]
---
# Slow

## Steps

1. CALL `slow_lookup` with the name `alpha`, alone in its response.
2. EXIT `done`.
