---
kind: edge
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner submits a provider search.
  entities: []
  contexts:
    web:
      place: web::manual-review
- kind: product
  text: The Product reports the failed lookup and keeps the audiobook values available for manual editing.
  entities:
  - entity: audiobook
    effect: reads
    facts:
    - Title
    - Author
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

# Show an unavailable provider

## Trigger

The chosen source cannot answer.

## Outcome

The Product reports the failed lookup and keeps the audiobook values available for manual editing.
