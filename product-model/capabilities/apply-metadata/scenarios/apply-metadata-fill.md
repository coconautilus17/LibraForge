---
kind: alternate
routes:
  web: Web
  cli: Command line
steps:
- kind: actor
  actor: library-owner
  text: The owner applies matching with the Fill missing fields only write mode.
  entities: []
  contexts:
    web:
      place: web::metadata-forge
    cli:
      place: cli
- kind: product
  text: The Product preserves populated audiobook values, fills gaps and records the affected metadata match
    fields; non-genre labels and dirty grouping names count as gaps.
  entities:
  - entity: audiobook
    effect: changes
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

# Fill genuine gaps

## Trigger

Existing tags include populated fields and missing values.

## Outcome

The Product preserves populated audiobook values, fills gaps and records the affected metadata match fields; non-genre labels and dirty grouping names count as gaps.
