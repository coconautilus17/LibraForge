---
appliesTo:
- type: entity
  id: genre-collection
  effect: changes
references:
- kind: code
  role: implementation
  target: app/genre_collections.py#plan_collections
permits:
- actors:
  - library-owner
  when:
  - fact: Managed by LibraForge
    is: true
---

# The library owner refreshes only LibraForge-managed genre collections

The library owner can refresh memberships only on collections carrying the LibraForge management marker. A same-named personal collection remains intact.
