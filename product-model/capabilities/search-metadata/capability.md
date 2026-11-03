---
availability:
- place: web
references:
- kind: code
  role: implementation
  target: app/main.py#search_audible_candidates
- kind: code
  role: implementation
  target: app/main.py#search_abs_candidates
- kind: code
  role: implementation
  target: app/main.py#search_abs_agg_candidates
- kind: code
  role: implementation
  target: app/main.py#search_abs_tract_candidates
- kind: code
  role: implementation
  target: app/static/m4b-tool.js
---

# Search metadata

Search a selected provider for candidate identities using the book clues or an explicit query; results from Audible's public catalog for a chosen marketplace, Audible through the connected account, Audiobookshelf, abs-agg, Goodreads (read directly) and Kindle covers through abs-tract support manual selection.
