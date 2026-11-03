---
kind: alternate
result: achieved
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  capability: browse-match-report
  text: The owner selects a reported ebook for Manual Review.
  entities:
  - entity: ebook
    effect: reads
    facts:
    - Path
  contexts:
    web:
      place: web::metadata-forge
- kind: product
  actor: library-owner
  capability: browse-match-report
  text: The Product carries the ebook target into Manual Review.
  entities:
  - entity: ebook
    effect: reads
    facts:
    - Path
  contexts:
    web:
      place: web::manual-review
- kind: product
  actor: library-owner
  capability: load-ebook
  text: The Product presents the ebook current fields.
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
- kind: actor
  actor: library-owner
  capability: apply-ebook-metadata
  text: The owner reviews and applies the ebook fields.
  entities:
  - entity: ebook
    effect: changes
    facts:
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
  actor: library-owner
  capability: apply-ebook-metadata
  text: The Product saves the ebook metadata.
  entities:
  - entity: ebook
    effect: changes
    facts:
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
references:
- kind: code
  role: implementation
  target: app/static/app.js#loadEbookReviewTarget
- kind: code
  role: implementation
  target: app/main.py#apply_manual_review_ebook_target
---

# Correct a reported ebook

## Trigger

The owner selects an ebook from Match Report.

## Outcome

The selected ebook has the owner’s reviewed metadata.
