---
availability:
- place: web
references:
- kind: code
  role: implementation
  target: app/main.py#enrichment_apply
- kind: code
  role: implementation
  target: app/main.py#_apply_book_via_abs
- kind: code
  role: implementation
  target: app/abs_client.py#reconcile_legacy_metadata_json
domain: enrichment-forge
---

# Apply enrichment

Write curated genres and explicitly chosen narrator or explicit values to included books through Audiobookshelf, leaving audio tags untouched.
