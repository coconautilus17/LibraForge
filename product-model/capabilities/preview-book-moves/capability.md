---
availability:
- place: web
- place: cli
references:
- kind: code
  role: implementation
  target: scripts/organize-audiobooks-by-metadata-v3_13.py#main
- kind: code
  role: implementation
  target: scripts/organize-audiobooks-by-metadata-v3_13.py#infer_metadata
- kind: code
  role: implementation
  target: app/main.py#build_organizer_command
domain: folder-forge
---

# Preview book moves

Build destinations from book metadata and a selected naming scheme, showing planned and skipped moves and reasons. Preview is the default.
