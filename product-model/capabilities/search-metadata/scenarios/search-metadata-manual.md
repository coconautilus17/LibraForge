---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner searches by title and author with a chosen provider.
  entities: []
  contexts:
    web:
      place: web::manual-review
- kind: product
  text: The Product presents metadata match candidates with identity, score, duration and cover information
    for comparison.
  entities:
  - entity: audiobook
    effect: reads
    facts:
    - Title
    - Author
    - Audio
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
  target: app/main.py#search_audible_candidates
- kind: code
  role: implementation
  target: app/main.py#search_abs_candidates
- kind: code
  role: implementation
  target: app/main.py#search_abs_agg_candidates
- kind: code
  role: implementation
  target: app/main.py#search_abs_tract_candidates
- kind: code
  role: implementation
  target: app/static/m4b-tool.js
---

# Compare provider candidates

## Trigger

A local book is loaded.

## Outcome

The Product presents metadata match candidates with identity, score, duration and cover information for comparison.

## Edge cases

- A provider failure is shown instead of a successful empty search.
- Kindle candidates provide cover information without substituting an ebook ASIN for an audiobook ASIN.
