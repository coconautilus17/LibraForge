---
kind: alternate
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner applies the failed row again.
  entities: []
  contexts:
    web:
      place: web::whole-library
- kind: product
  text: The Product attempts the included audio books again and marks the enrichment result Applied when every
    attempt succeeds.
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
    from: Apply failed
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

# Retry a partially applied row

## Trigger

A prior application left an Apply failed row.

## Outcome

The Product attempts the included audio books again and marks the enrichment result Applied when every attempt succeeds.
