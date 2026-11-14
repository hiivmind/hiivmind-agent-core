---
name: survey
description: Survey the eight items of the corpus and record the user's favourite. Used to make a long session.
inputs:
  favourite: the user's favourite item
outputs:
  favourite: {type: string, description: the user's favourite item}
  items_seen: {type: integer, description: how many items were surveyed}
exits: [done, declined, failed]
allowed-tools: [tools__shell]
---
# Survey

Corpus: {{settings.CORPUS_NAME}}.
Progress so far: {{node.progress}}.
Favourite: {{input.favourite}}.

## Steps

1. For each N from 1 to 8, in order, one item per response: CALL `tools__shell` with the command `echo item-N of {{settings.CORPUS_NAME}}`, then STATE.set `progress` to `N of 8`. "Progress so far" above tells you where you are; continue from the next item and never redo an item.
2. When progress reads `8 of 8` and "Favourite" above reads "not given", ASK "Which item is your favourite?". When the user answers, STATE.set `favourite` to the answer.
3. EXIT `done` with outputs `favourite` (the answer) and `items_seen` (8).
