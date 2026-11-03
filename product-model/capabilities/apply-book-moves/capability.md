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
  target: scripts/organize-audiobooks-by-metadata-v3_13.py#execute_planned_move
- kind: code
  role: implementation
  target: app/static/organizer.js#showOrgApplyConfirm
domain: folder-forge
---

# Apply book moves

Recompute destinations from current inputs and execute eligible relocations with companion handling and per-move results. The web asks for confirmation of source and destination.
