---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner searches a folder for multipart or non-M4B books.
  entities: []
  contexts:
    web:
      place: web::m4b-tool
- kind: product
  text: The Product lists audiobook conversion candidates with files, formats, reasons and discovery freshness.
  entities:
  - entity: audiobook
    effect: reads
    facts:
    - Path
    - Audio
  contexts:
    web:
      place: web::m4b-tool
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#discover_m4b_candidates
- kind: code
  role: implementation
  target: app/conversion_discovery.py#conversion_candidate
---

# Find conversion candidates

## Trigger

The owner has audio to consolidate.

## Outcome

The Product lists audiobook conversion candidates with files, formats, reasons and discovery freshness.

## Edge cases

- Missing or stale cached results require rebuilding discovery.
- An empty search produces no candidates, not a fabricated conversion task.
