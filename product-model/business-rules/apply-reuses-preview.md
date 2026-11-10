---
appliesTo:
- type: capability
  id: apply-metadata
- type: capability
  id: preview-metadata
references:
- kind: code
  role: implementation
  target: app/fixer/plan.py
- kind: code
  role: implementation
  target: scripts/audible-metadata-fixer-v5.py#main
---

# Apply writes what the preview showed

Apply reuses the latest covering preview's metadata match for each book whose audio files are unchanged since that preview and whose preview used the same matching settings. The checks that run before any search still come first, and any other book is searched.
