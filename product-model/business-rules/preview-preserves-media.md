---
appliesTo:
- type: capability
  id: preview-metadata
- type: capability
  id: preview-book-moves
- type: capability
  id: preview-legacy-metadata-migration
- type: capability
  id: preview-author-normalization
- type: capability
  id: scan-library
references:
- kind: code
  role: implementation
  target: scripts/audible-metadata-fixer-v5.py#main
- kind: code
  role: implementation
  target: scripts/organize-audiobooks-by-metadata-v3_13.py#main
---

# Previews and scans do not change books

Metadata and organizer previews and library scans compute proposed work without applying it to books, and write nothing next to the books: their reports and working caches stay with the Product's own reports. Explicit apply, direct edits, restoration, conversion and downloading are distinct actions.
