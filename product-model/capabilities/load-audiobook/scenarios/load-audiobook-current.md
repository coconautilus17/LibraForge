---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner loads the selected book.
  entities: []
  contexts:
    web:
      place: web::manual-review
- kind: product
  text: The Product presents the audiobook’s current metadata, cover, grouping and duration together with search
    clues.
  entities:
  - entity: audiobook
    effect: reads
    facts:
    - Path
    - Title
    - Author
    - Narrator
    - Series
    - Publication
    - Identifiers
    - Genres
    - Explicit
    - Summary
    - Cover
    - Audio
    - Metadata status
    - Original metadata
  contexts:
    web:
      place: web::manual-review
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#inspect_manual_review_target
---

# Inspect current metadata

## Trigger

A local target is selected.

## Outcome

The Product presents the audiobook’s current metadata, cover, grouping and duration together with search clues.

## Edge cases

- A folder containing several distinct books is refused as a single review target.
- Loading original tags uses the saved backup for comparison without restoring it.
