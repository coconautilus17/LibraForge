---
kind: edge
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner chooses Apply for the reviewed enrichment result.
  entities:
  - entity: enrichment-result
    effect: reads
    facts:
    - Subject
    - Genres
    - Evidence
    - Pinned genres
    - Narrator
    - Explicit choices
    - Included books
    - Apply result
  contexts:
    web:
      place: web::enrichment-forge
- kind: product
  text: The Product records an Apply failed enrichment result with the failed books while retaining successful
    changes to the other audiobook items.
  entities:
  - entity: enrichment-result
    effect: changes
    facts:
    - Apply result
    from: Compiled
    to: Apply failed
  - entity: audiobook
    effect: changes
    facts:
    - Genres
    - Narrator
    - Explicit
  contexts:
    web:
      place: web::enrichment-forge
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#enrichment_apply
- kind: code
  role: implementation
  target: app/main.py#_apply_book_via_abs
- kind: code
  role: implementation
  target: app/abs_client.py#reconcile_legacy_metadata_json
---

# Report per-book apply failures

## Trigger

At least one included book cannot be written.

## Outcome

The Product records an Apply failed enrichment result with the failed books while retaining successful changes to the other audiobook items.
