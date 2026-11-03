---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner chooses the included books, the shared fields and each book’s number, then applies.
  entities: []
  contexts:
    web:
      place: web::manual-review
- kind: product
  text: The Product changes the series shared metadata and the included audiobook fields, preserving blank
    shared fields and reporting each book’s result.
  entities:
  - entity: series
    effect: changes
    facts:
    - Name
    - Authors
    - Books
    - Shared metadata
  - entity: audiobook
    effect: changes
    facts:
    - Author
    - Narrator
    - Series
    - Genres
    - Publication
    - Explicit
    - Metadata status
    - Companions
  contexts:
    web:
      place: web::manual-review
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#apply_series_group
- kind: code
  role: implementation
  target: app/static/fix-series.js
---

# Correct a detected series

## Trigger

The report has identified a series group.

## Outcome

The Product changes the series shared metadata and the included audiobook fields, preserving blank shared fields and reporting each book’s result.

## Edge cases

- Explicit changes apply only when that control has been deliberately set.
- One failed book does not prevent corrections to the remaining books.
