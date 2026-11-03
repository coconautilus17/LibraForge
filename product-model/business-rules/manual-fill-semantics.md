---
appliesTo:
- type: capability
  id: apply-metadata-match
- type: capability
  id: fix-series
- type: capability
  id: apply-metadata
references:
- kind: code
  role: implementation
  target: app/main.py#apply_series_group
- kind: code
  role: implementation
  target: app/main.py#_write_book_metadata
- kind: code
  role: implementation
  target: scripts/audible-metadata-fixer-v5.py#merge_fill_missing_metadata
---

# Manual Apply Fill preserves blank inputs

Manual Apply Fill and Fix Series write filled values even over populated fields; an empty shared or selected field means leave it alone. Batch Fill missing instead preserves already-populated values, subject to cleanup of non-genres and dirty series names.
