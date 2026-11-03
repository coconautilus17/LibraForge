---
entities:
- entity: genre-collection
  shows:
  - Name
  - Library
  - Books
  - Managed by LibraForge
entryPoints:
- web: /enrichment-forge
references:
- kind: code
  role: implementation
  target: app/main.py#enrichment_collections_plan
---

# Collections from genres

Review collection membership changes from current library genres and delete collections LibraForge created.
