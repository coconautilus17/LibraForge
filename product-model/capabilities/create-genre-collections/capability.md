---
availability:
- place: web
references:
- kind: code
  role: implementation
  target: app/main.py#enrichment_collections_apply
- kind: code
  role: implementation
  target: app/genre_collections.py#apply_collection_plan
domain: enrichment-forge
---

# Create genre collections

Create absent selected genre collections and mark them as managed by LibraForge. A genre over the size limit is created as numbered parts.
