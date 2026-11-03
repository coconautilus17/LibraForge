---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner edits title, author and any other fields and saves.
  entities: []
  contexts:
    web:
      place: web::manual-review
- kind: product
  text: The Product changes audiobook metadata with overwrite semantics, uses a selected replacement cover
    and retains the manually applied provenance.
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
    - Explicit
    - Summary
    - Cover
    - Metadata status
    - Companions
  contexts:
    web:
      place: web::manual-review
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#edit_manual_review_book
- kind: code
  role: implementation
  target: app/main.py#upload_manual_review_cover
- kind: code
  role: implementation
  target: app/static/manual-review-edit.js
---

# Save direct corrections

## Trigger

The loaded book needs a correction.

## Outcome

The Product changes audiobook metadata with overwrite semantics, uses a selected replacement cover and retains the manually applied provenance.

## Edge cases

- Title and author are required.
- Cover upload accepts JPEG or PNG up to 10 MiB; rejected input leaves the book unchanged.
- The ffmpeg blank-clearing warning applies here too.
