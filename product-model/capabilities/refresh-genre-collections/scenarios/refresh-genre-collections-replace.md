---
kind: alternate
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner applies a selected genre whose plan replaces an existing LibraForge collection.
  entities: []
  contexts:
    web:
      place: web::genre-collections
- kind: product
  text: The Product removes the replaced genre collection and reports how many were removed.
  entities:
  - entity: genre-collection
    effect: removes
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

# Delete a replaced collection on apply

## Trigger

A LibraForge collection of a selected genre is no longer in the plan: the genre is now split into parts, a part is no longer needed, or the genre is Progression Fantasy.

## Outcome

The Product removes the replaced genre collection and reports how many were removed.

## Edge cases

- A collection without the LibraForge marker is never removed this way.
