---
kind: alternate
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner chooses Full Overwrite with the reviewed fields.
  entities: []
  contexts:
    web:
      place: web::manual-review
- kind: product
  text: The Product writes the audiobook values exactly, including supported blank-field clears, and records
    the metadata match write outcome.
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
    - Summary
    - Cover
    - Metadata status
    - Original metadata
    - Companions
  - entity: metadata-match
    effect: changes
    facts:
    - Write outcome
  contexts:
    web:
      place: web::manual-review
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#apply_manual_review_result
- kind: code
  role: implementation
  target: app/main.py#_write_book_metadata
- kind: code
  role: implementation
  target: app/static/app.js
---

# Clear fields intentionally

## Trigger

The owner wants exact replacement values on a supported tagged file.

## Outcome

The Product writes the audiobook values exactly, including supported blank-field clears, and records the metadata match write outcome.
