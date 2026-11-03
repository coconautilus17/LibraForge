---
appliesTo:
- type: entity
  id: planned-move
references:
- kind: code
  role: implementation
  target: scripts/organize-audiobooks-by-metadata-v3_13.py#plan_folder_move
- kind: code
  role: implementation
  target: scripts/organize-audiobooks-by-metadata-v3_13.py#plan_loose_file_move
- kind: code
  role: implementation
  target: scripts/organize-audiobooks-by-metadata-v3_13.py#main
---

# Default organization skips occupied destinations

The default organizer does not merge into an occupied book destination. Existing and within-run conflicts become skipped review entries; one failed move does not abort other moves.
