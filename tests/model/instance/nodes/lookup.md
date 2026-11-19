---
name: lookup
description: Look up the revision of a name in the register.
inputs:
  name: the name to look up
outputs:
  revision: {type: string, description: the revision of the name}
exits: [done, failed]
allowed-tools: [lookup_revision]
preconditions:
  - tool: known_name
    args: {name: "{{input.name}}"}
    message: "The register does not hold {{input.name}}."
---
# Lookup

Name to look up: {{input.name}}.

## Steps

1. CALL `lookup_revision`.
2. EXIT `done`.
