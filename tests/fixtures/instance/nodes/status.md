---
name: status
description: Report the status of the corpus named in the settings.
inputs: {}
outputs:
  status_report: {type: string, description: one line describing the corpus status}
exits: [done, failed]
allowed-tools: [tools__shell]
---
# Status

Corpus: {{settings.CORPUS_NAME}}.

## Steps

1. CALL `tools__shell` with the command `echo status ok for {{settings.CORPUS_NAME}}`.
2. In one response, tell the user the status in one line and EXIT `done` with output `status_report` (that line).
