---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner opens the Suspicion Report.
  entities: []
  contexts:
    web:
      place: web::metadata-forge
- kind: product
  text: The Product presents the metadata match review reasons and series correction candidates.
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
  - entity: series
    effect: reads
    facts:
    - Name
    - Authors
    - Books
    - Shared metadata
  contexts:
    web:
      place: web::metadata-forge
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#get_suspect_review
- kind: code
  role: implementation
  target: app/static/ui-common.js
---

# Read matching suspicions

## Trigger

A suspicion review has been generated.

## Outcome

The Product presents the metadata match review reasons and series correction candidates.
