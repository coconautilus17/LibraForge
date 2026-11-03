---
appliesTo:
- type: entity
  id: audiobook
  facts:
  - Metadata status
references:
- kind: code
  role: implementation
  target: scripts/audible-metadata-fixer-v5.py#should_skip_due_to_marker
- kind: code
  role: implementation
  target: app/tests/test_fixer_v5_manually_applied_never_downgraded.py
---

# Batch reprocessing preserves a manually selected match

A manually applied identity is retained during ordinary batch reprocessing, including force requests. A deliberate manual correction or original-metadata restoration remains available.
