---
kind: alternate
routes:
  web: Web
  cli: Command line
steps:
- kind: actor
  actor: library-owner
  text: The owner applies matching with the Smart write mode.
  entities: []
  contexts:
    web:
      place: web::metadata-forge
    cli:
      place: cli
- kind: product
  text: The Product keeps matching audiobook tags and records an unchanged metadata match outcome; companion
    metadata can still be supplied when it is missing.
  entities:
  - entity: audiobook
    effect: reads
    facts:
    - Title
    - Author
    - Narrator
    - Series
    - Publication
    - Identifiers
    - Genres
  - entity: metadata-match
    effect: changes
    facts:
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
  target: scripts/audible-metadata-fixer-v5.py#main
- kind: code
  role: implementation
  target: scripts/audible-metadata-fixer-v5.py#decide_write
- kind: code
  role: implementation
  target: app/abs_client.py#sync_book_metadata
---

# Skip already-matching tags

## Trigger

The selected Smart comparison finds the written fields already match.

## Outcome

The Product keeps matching audiobook tags and records an unchanged metadata match outcome; companion metadata can still be supplied when it is missing.
