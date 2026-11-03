---
availability:
- place: web
references:
- kind: code
  role: implementation
  target: app/main.py#apply_series_group
- kind: code
  role: implementation
  target: app/static/fix-series.js
domain: metadata-forge
---

# Fix Series

Apply shared fields and per-book sequence corrections to included members of a detected series group. Filled shared values replace old ones; blank shared values are left alone.
