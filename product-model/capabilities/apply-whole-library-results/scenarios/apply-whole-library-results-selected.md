---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner ticks rows and applies them.
  entities: []
  contexts:
    web:
      place: web::whole-library
- kind: product
  text: The Product changes eligible audiobook genres and authoritative opted-in explicit values and marks
    the enrichment result Applied.
  entities:
  - entity: audiobook
    effect: changes
    facts:
    - Genres
    - Explicit
  - entity: enrichment-result
    effect: changes
    facts:
    - Apply result
    from: Compiled
    to: Applied
  contexts:
    web:
      place: web::whole-library
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#enrichment_batch_apply
- kind: code
  role: implementation
  target: app/enrichment_batch.py#apply_batch
---

# Apply selected proposals

## Trigger

Compilation is stopped and selected results are ready.

## Outcome

The Product changes eligible audiobook genres and authoritative opted-in explicit values and marks the enrichment result Applied.

## Edge cases

- Applied rows are skipped; items without audio are never written.
- Starting or applying another batch while this application is active is refused.
- Bulk application never sets a shared narrator.
