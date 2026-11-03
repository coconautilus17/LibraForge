---
kind: edge
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner chooses Full Overwrite.
  entities: []
  contexts:
    web:
      place: web::manual-review
- kind: product
  text: The Product applies nonblank audiobook fields and returns a warning that blank tags were left untouched.
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

# Explain limited blank clearing

## Trigger

The file requires the ffmpeg writer.

## Outcome

The Product applies nonblank audiobook fields and returns a warning that blank tags were left untouched.
