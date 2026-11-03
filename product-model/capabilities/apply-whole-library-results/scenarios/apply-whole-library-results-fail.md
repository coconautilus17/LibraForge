---
kind: edge
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner applies the ticked rows.
  entities: []
  contexts:
    web:
      place: web::whole-library
- kind: product
  text: The Product marks the enrichment result Apply failed and records the individual errors while continuing
    the other books.
  entities:
  - entity: enrichment-result
    effect: changes
    facts:
    - Apply result
    from: Compiled
    to: Apply failed
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

# Keep failures available for retry

## Trigger

One selected book fails to write.

## Outcome

The Product marks the enrichment result Apply failed and records the individual errors while continuing the other books.
