---
kind: edge
routes:
  web: Web
  cli: Command line
steps:
- kind: actor
  actor: library-owner
  text: The owner starts matching for the folder.
  entities: []
  contexts:
    web:
      place: web::metadata-forge
    cli:
      place: cli
- kind: product
  text: The Product records the metadata match as needing review and leaves the audiobook metadata unchanged.
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
  - entity: audiobook
    effect: reads
    facts:
    - Path
    - Title
    - Author
    - Series
    - Identifiers
    - Audio
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

# Keep an unresolved identity for review

## Trigger

Candidates tie and duration evidence cannot resolve them.

## Outcome

The Product records the metadata match as needing review and leaves the audiobook metadata unchanged.

## Edge cases

- The tags or embedded ASIN point to one recording while the runtime matches another listing of the same title and author; neither is applied.
