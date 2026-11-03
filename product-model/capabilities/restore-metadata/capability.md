---
availability:
- place: web
- place: cli
references:
- kind: code
  role: implementation
  target: scripts/audible-metadata-fixer-v5.py#restore_metadata_backups
- kind: code
  role: implementation
  target: scripts/audible-metadata-fixer-v5.py#restore_metadata_from_backup
- kind: code
  role: implementation
  target: app/main.py#build_command
domain: metadata-forge
---

# Restore metadata

Restore saved original embedded metadata for local files. Files without a usable backup are skipped.
