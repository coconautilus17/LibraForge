---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner loads the ebook for review.
  entities:
  - entity: ebook
    effect: reads
    facts:
    - Path
    - Title
    - Author
    - Series
    - Publication
    - Genres
    - Summary
    - Cover
    - Metadata status
  contexts:
    web:
      place: web::manual-review
- kind: product
  text: The Product presents the ebook’s existing fields, paired formats and provider candidate without writing
    them.
  entities:
  - entity: ebook
    effect: reads
    facts:
    - Path
    - Title
    - Author
    - Series
    - Publication
    - Genres
    - Summary
    - Cover
    - Metadata status
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
      place: web::manual-review
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#load_manual_review_ebook_target
- kind: code
  role: implementation
  target: app/main.py#match_ebook_unit
---

# Review ebook metadata

## Trigger

An ebook result is selected.

## Outcome

The Product presents the ebook’s existing fields, paired formats and provider candidate without writing them.
