---
name: refresh
description: Refresh the sources of the corpus named in the settings.
inputs:
  sources: which sources to update
outputs:
  sources_updated: {type: string, description: the sources that were updated}
  branch: {type: string, description: the branch the update was made on}
exits: [done, declined, failed]
allowed-tools: [tools__shell]
---
# Refresh

Corpus: {{settings.CORPUS_NAME}} in {{settings.CORPUS_PATH}}.
Sources to update: {{input.sources}}.
Branch: {{session.branch}}.
Token: {{settings.GITHUB_TOKEN}}.
{{include fragments/safety.md}}

## Steps

1. CALL `tools__shell` with the command `echo checked {{settings.CORPUS_NAME}}`. Do this once only.
2. If "Sources to update" above reads "not given", ASK "Which sources should I update?". When the user answers the question, STATE.set `sources` to the answer.
3. STATE.set `branch` to `refresh/{{settings.CORPUS_NAME}}`.
4. CALL `tools__shell` with the command `echo updating` followed by the sources.
5. EXIT `done` with outputs `sources_updated` (the sources) and `branch` (the branch).
