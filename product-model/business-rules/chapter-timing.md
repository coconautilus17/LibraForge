---
appliesTo:
- type: entity
  id: chapter
  facts:
  - Timing
  - Title
  - Manual
references:
- kind: code
  role: implementation
  target: app/main.py#save_chaptering
---

# Saved chapter times are ordered and nonnegative

Saving orders entries by start, clamps starts to zero or later and ends to at least the start, assigns sequential positions and fills empty labels. Saved manual edits retain their manual attribution.
