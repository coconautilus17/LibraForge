---
availability:
- place: cli
references:
- kind: code
  role: implementation
  target: scripts/normalize-author-names.py#main
- kind: code
  role: implementation
  target: scripts/normalize-author-names.py#apply_folder_change
domain: author-names
---

# Apply author normalization

Apply the explicit local naming migration, recording changed metadata and folder operations in a reversible change log. Embedded tag updates are opt-in.
