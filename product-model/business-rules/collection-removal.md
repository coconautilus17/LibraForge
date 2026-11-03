---
appliesTo:
- type: entity
  id: genre-collection
  effect: removes
references:
- kind: code
  role: implementation
  target: app/main.py#enrichment_collection_delete
- kind: code
  role: implementation
  target: app/genre_collections.py#is_managed
permits:
- actors:
  - library-owner
  when:
  - fact: Managed by LibraForge
    is: true
---

# The library owner deletes only LibraForge-managed genre collections

The library owner can delete a collection only when it carries the LibraForge management marker. Deleting it removes the collection from Audiobookshelf; its books stay in the library. Any other collection is refused.
