---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner reads the Suspicion Report above the planned moves.
  entities:
  - entity: planned-move
    effect: reads
    facts:
    - Source
    - Destination
    - Metadata
    - Review reasons
    - Companions
    - Result
  contexts:
    web:
      place: web::folder-forge
- kind: product
  text: The Product presents the metadata match review reasons associated with the reviewed books.
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
      place: web::folder-forge
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#get_suspect_review
- kind: code
  role: implementation
  target: app/static/ui-common.js
---

# Read suspicions while planning

## Trigger

A review is available from Folder Forge.

## Outcome

The Product presents the metadata match review reasons associated with the reviewed books.
