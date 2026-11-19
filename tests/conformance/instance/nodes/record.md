---
name: record
description: Record working values and a note.
inputs: {}
outputs:
  note: {type: string, description: the note recorded}
exits: [done, failed]
allowed-tools: []
---
# Record

## Steps

1. STATE.set `note`, then EXIT `done`.
