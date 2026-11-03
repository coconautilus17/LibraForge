---
appliesTo:
- type: capability
  id: apply-metadata
- type: capability
  id: apply-metadata-match
- type: capability
  id: edit-audiobook
- type: capability
  id: apply-enrichment
references:
- kind: code
  role: implementation
  target: app/abs_client.py#apply_genre_ownership
- kind: code
  role: implementation
  target: app/main.py#_apply_book_via_abs
---

# Metadata matching preserves established library genres

Metadata Forge supplies genres to Audiobookshelf when real library genres are absent. Deliberate Enrichment Forge curation is the path for replacing established library genres.
