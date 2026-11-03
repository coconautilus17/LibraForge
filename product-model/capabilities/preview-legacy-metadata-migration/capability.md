---
availability:
- place: cli
references:
- kind: code
  role: implementation
  target: scripts/migrate-legacy-metadata-json.py#main
- kind: code
  role: implementation
  target: app/abs_client.py#plan_legacy_metadata_json_migration
---

# Preview legacy metadata migration

Compare legacy local metadata files with Audiobookshelf records and report which files are identical, older, newer or unreadable.
