---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner chooses Apply for the curated enrichment result.
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
  text: The Product changes the included audiobook library genres and selected narrator or explicit values,
    and marks the enrichment result Applied with its outcome.
  entities:
  - entity: audiobook
    effect: changes
    facts:
    - Genres
    - Narrator
    - Explicit
    - Companions
  - entity: enrichment-result
    effect: changes
    facts:
    - Apply result
    from: Compiled
    to: Applied
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

# Apply a curated series

## Trigger

The owner has reviewed the included books and proposed fields.

## Outcome

The Product changes the included audiobook library genres and selected narrator or explicit values, and marks the enrichment result Applied with its outcome.

## Edge cases

- Blank genre and narrator choices leave those fields untouched.
- Existing legacy metadata files are compared with the current library record before removal, using the newer side’s nonblank values.
- Curating and applying a series marks its whole-library result applied so later bulk application does not replace it.
