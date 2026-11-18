---
name: plain
description: Do the plain work of the corpus. Used to test a node whose frontmatter has no allowed-tools line.
inputs: {}
outputs:
  done_work: {type: string, description: what was done}
exits: [done, failed]
---
# Plain

## Steps

1. CALL `tools__shell` with the command `echo plain-work`.
2. EXIT `done` with output `done_work` set to `plain-work`.
