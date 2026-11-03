---
kind: edge
routes:
  web: Web
  cli: Command line
steps:
- kind: actor
  actor: library-owner
  text: The owner starts matching with the Goodreads fallback on.
  entities: []
  contexts:
    web:
      place: web::metadata-forge
    cli:
      place: cli
- kind: product
  text: The Product marks the metadata match with the rate-limit condition so skipped fallback lookups remain
    distinguishable from genuine no-match results.
  entities:
  - entity: metadata-match
    effect: creates
    facts:
    - Book
    - Candidate
    - Provider
    - Score
    - Edit mode
    - Review reasons
    - Write outcome
  contexts:
    web:
      place: web::metadata-forge
    cli:
      place: cli
  actor: library-owner
references:
- kind: code
  role: implementation
  target: scripts/audible-metadata-fixer-v5.py#search_item
- kind: code
  role: implementation
  target: scripts/audible-metadata-fixer-v5.py#main
- kind: code
  role: implementation
  target: app/main.py#build_command
---

# Distinguish limited fallback from no match

## Trigger

Goodreads requests meet the source cooldown.

## Outcome

The Product marks the metadata match with the rate-limit condition so skipped fallback lookups remain distinguishable from genuine no-match results.
