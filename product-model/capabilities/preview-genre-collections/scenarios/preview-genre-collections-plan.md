---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner opens Collections from genres.
  entities: []
  contexts:
    web:
      place: web::genre-collections
- kind: product
  text: The Product reads genre collection membership and presents additions and removals based on a fresh
    read of library genres.
  entities:
  - entity: genre-collection
    effect: reads
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
  target: app/main.py#_collections_plan
- kind: code
  role: implementation
  target: app/genre_collections.py#plan_collections
---

# Review collection membership

## Trigger

Audiobookshelf is connected.

## Outcome

The Product reads genre collection membership and presents additions and removals based on a fresh read of library genres.

## Edge cases

- An unmarked collection with the same name is reported as name taken and left alone.
- A LibraForge collection the plan no longer has, such as an unsplit genre now in parts or a Progression Fantasy collection, is listed to be deleted on apply.
