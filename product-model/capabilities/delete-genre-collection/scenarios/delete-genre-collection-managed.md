---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner chooses Delete on a listed collection and confirms.
  entities: []
  contexts:
    web:
      place: web::genre-collections
- kind: product
  text: The Product removes the genre collection from Audiobookshelf and lists the collections again.
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
  target: app/main.py#enrichment_collection_delete
- kind: code
  role: implementation
  target: app/static/enrichment-forge.js#deleteCollection
---

# Delete a LibraForge collection

## Trigger

A collection LibraForge created is no longer wanted.

## Outcome

The Product removes the genre collection from Audiobookshelf and lists the collections again.

## Edge cases

- A collection without the LibraForge marker is refused and left alone.
- When Audiobookshelf is not configured or the collection is not found, the deletion fails with that reason.
