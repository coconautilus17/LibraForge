---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner applies the planned new collections.
  entities: []
  contexts:
    web:
      place: web::genre-collections
- kind: product
  text: The Product creates the genre collection with current matching book membership and its LibraForge marker.
  entities:
  - entity: genre-collection
    effect: creates
    facts:
    - Name
    - Library
    - Books
    - Managed by LibraForge
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

# Create a managed genre collection

## Trigger

The preview has a selected genre with books and no existing named collection.

## Outcome

The Product creates the genre collection with current matching book membership and its LibraForge marker.

## Edge cases

- Empty genres and occupied personal collection names are skipped; per-collection failures are reported.
