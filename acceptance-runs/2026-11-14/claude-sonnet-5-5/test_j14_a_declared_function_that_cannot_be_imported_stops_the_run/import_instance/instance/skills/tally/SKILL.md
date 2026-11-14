---
name: tally
description: Count the words of the corpus motto. Used to test a tool that is a plain Python function.
inputs: {}
outputs:
  words: {type: integer, description: how many words the motto has}
exits: [done, failed]
allowed-tools: [count_words]
---
# Tally

## Steps

1. CALL `count_words` with `text` set to `one two three four five`.
2. EXIT `done` with output `words` set to the number the tool returned.
