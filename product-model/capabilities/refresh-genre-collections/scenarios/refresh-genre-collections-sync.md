---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner applies the planned membership changes.
  entities: []
  contexts:
    web:
      place: web::genre-collections
- kind: product
  text: The Product changes genre collection membership by adding and removing the planned books and reports
    the outcome.
  entities:
  - entity: genre-collection
    effect: changes
    facts:
    - Books
  contexts:
    web:
      place: web::genre-collections
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#enrichment_collections_apply
- kind: code
  role: implementation
  target: app/genre_collections.py#apply_collection_plan
---

# Refresh managed membership

## Trigger

A marked collection has membership changes.

## Outcome

The Product changes genre collection membership by adding and removing the planned books and reports the outcome.

## Edge cases

- In-sync or empty plans are skipped. A failing collection does not stop the others.
