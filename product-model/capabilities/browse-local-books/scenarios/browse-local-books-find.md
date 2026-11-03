---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner types a title into the search or browses a library folder.
  entities: []
  contexts:
    web:
      place: web::manual-review
- kind: product
  text: The Product presents matching audiobook paths and allows the selected book to be loaded for Manual
    Review.
  entities:
  - entity: audiobook
    effect: reads
    facts:
    - Path
    - Title
    - Author
  contexts:
    web:
      place: web::manual-review
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#manual_review_search
- kind: code
  role: implementation
  target: app/main.py#browse_manual_review_path
- kind: code
  role: implementation
  target: app/static/app.js
---

# Find a local title

## Trigger

The owner wants to review a particular book.

## Outcome

The Product presents matching audiobook paths and allows the selected book to be loaded for Manual Review.

## Edge cases

- The search index can still be building; its current count and state remain visible.
- A search with no match returns no books.
