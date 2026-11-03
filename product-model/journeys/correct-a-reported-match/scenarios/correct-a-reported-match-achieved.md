---
kind: primary
result: achieved
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  capability: browse-match-report
  text: The owner selects a metadata match for manual review.
  entities:
  - entity: metadata-match
    effect: reads
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
      place: web::metadata-forge
- kind: product
  actor: library-owner
  capability: browse-match-report
  text: The Product carries the selected audiobook target into Manual Review.
  entities:
  - entity: audiobook
    effect: reads
    facts:
    - Path
  contexts:
    web:
      place: web::manual-review
- kind: product
  actor: library-owner
  capability: load-audiobook
  text: The Product presents the audiobook current metadata.
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
- kind: actor
  actor: library-owner
  capability: apply-metadata-match
  text: The owner reviews and applies a chosen metadata match.
  entities:
  - entity: metadata-match
    effect: reads
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
- kind: product
  actor: library-owner
  capability: apply-metadata-match
  text: The Product changes the audiobook fields and records the metadata match write outcome.
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
references:
- kind: code
  role: implementation
  target: app/static/app.js#renderManualReviewList
- kind: code
  role: implementation
  target: app/static/app.js#loadManualTarget
- kind: code
  role: implementation
  target: app/main.py#apply_manual_review_result
---

# Correct a reported match successfully

## Trigger

The Match Report shows a result the owner doubts.

## Outcome

The selected book has the owner’s reviewed metadata.
