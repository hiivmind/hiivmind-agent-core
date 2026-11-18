---
name: shape
description: Count the words the shell echoes. Used to test the output check; its procedure asks for a shape its schema does not allow.
inputs: {}
outputs:
  count: {type: integer, description: how many words were echoed}
exits: [done, failed]
allowed-tools: [tools__shell]
---
# Shape

## Steps

1. CALL `tools__shell` with the command `echo one two three`.
2. EXIT `done` with output `count`: the number of words echoed, written out as an English word in a string (for example "two").
3. If the outputs are rejected, correct them so that they fit the schema and EXIT again. Do not ask the person.
