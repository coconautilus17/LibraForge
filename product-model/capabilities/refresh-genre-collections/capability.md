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

# Refresh genre collections

Refresh memberships of existing LibraForge-managed genre collections using current library genres, deleting the LibraForge collections of a selected genre that the plan replaced.
