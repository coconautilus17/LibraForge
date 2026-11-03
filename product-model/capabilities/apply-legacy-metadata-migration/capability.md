---
availability:
- place: cli
references:
- kind: code
  role: implementation
  target: scripts/migrate-legacy-metadata-json.py#main
- kind: code
  role: implementation
  target: app/abs_client.py#apply_legacy_metadata_json_migration
- kind: code
  role: implementation
  target: app/abs_client.py#reconcile_legacy_metadata_json
---

# Apply legacy metadata migration

Back up each legacy metadata file before reconciling it into Audiobookshelf and removing it; keep unreadable files and report per-book failures.
