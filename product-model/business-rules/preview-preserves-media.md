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
references:
- kind: code
  role: implementation
  target: scripts/audible-metadata-fixer-v5.py#main
- kind: code
  role: implementation
  target: scripts/organize-audiobooks-by-metadata-v3_13.py#main
---

# Preview does not apply book metadata or moves

Metadata and organizer previews compute proposed work without applying it to books. Reports and working caches can still be saved. Explicit apply, direct edits, restoration, conversion and downloading are distinct actions.
