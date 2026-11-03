---
availability:
- place: web
references:
- kind: code
  role: implementation
  target: app/main.py#_compile_unit
- kind: code
  role: implementation
  target: app/enrichment.py#compile_series_enrichment
- kind: code
  role: implementation
  target: app/genre_voting.py
domain: enrichment-forge
---

# Compile enrichment

Compile sources for a series or standalone book into an editable genre and explicit-content proposal. Audible is searched through the connected account, or its public catalog when there is none, and Audiobookshelf’s Audible search is used only when Audible fails; Goodreads, AudioSilo, Open Library, description keywords and series catalogs add evidence.
