---
availability:
- place: web
- place: cli
references:
- kind: code
  role: implementation
  target: scripts/audible-metadata-fixer-v5.py#main
- kind: code
  role: implementation
  target: scripts/audible-metadata-fixer-v5.py#decide_write
- kind: code
  role: implementation
  target: app/abs_client.py#sync_book_metadata
domain: metadata-forge
---

# Apply metadata matching

Apply eligible batch matches according to Smart, Fill missing or Overwrite mode; write local tags and companion metadata, or only the configured metadata destination.
