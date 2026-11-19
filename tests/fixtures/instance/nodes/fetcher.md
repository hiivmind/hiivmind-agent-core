---
name: fetcher
description: Fetch one page for the corpus. Used to test a tool server that cannot be reached.
inputs: {}
outputs:
  page: {type: string, description: what the fetch returned}
exits: [done, failed]
allowed-tools: [web__fetch]
---
# Fetcher

## Steps

1. CALL `web__fetch` with `url` set to `https://example.org/a`.
2. If the call returned an error, EXIT `failed` with `reason` set to the error. Do not try again.
3. Otherwise EXIT `done` with output `page` set to what the tool returned.
