---
appliesTo:
- type: entity
  id: planned-move
  facts:
  - Destination
references:
- kind: code
  role: implementation
  target: scripts/organize-audiobooks-by-metadata-v3_13.py#naming_template_filename_for_item
- kind: code
  role: implementation
  target: scripts/organize-audiobooks-by-metadata-v3_13.py#execute_planned_move
---

# Multipart books retain their chapter filenames

Custom filename templates apply to true single-file books. A multipart book can change its destination folder while retaining the distinct chapter filenames.
