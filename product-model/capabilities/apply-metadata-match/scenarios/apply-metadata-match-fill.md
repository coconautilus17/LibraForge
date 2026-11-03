---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner reviews the selected metadata match and chooses Apply Fill.
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
  text: The Product changes populated audiobook fields even when old values existed, preserves blank inputs
    and records the metadata match as manually applied.
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

# Apply selected populated fields

## Trigger

The owner has chosen a candidate.

## Outcome

The Product changes populated audiobook fields even when old values existed, preserves blank inputs and records the metadata match as manually applied.

## Edge cases

- A result missing title or author is rejected.
- Series-only mode retains the local book identity rather than treating a series match as a full book match.
