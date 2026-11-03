---
appliesTo:
- type: entity
  id: enrichment-result
  facts:
  - Pinned genres
  - Genres
references:
- kind: code
  role: implementation
  target: app/enrichment.py#detect_manual_genres
- kind: code
  role: implementation
  target: app/enrichment.py#without_matcher_genres
- kind: code
  role: implementation
  target: app/genre_voting.py#vote_unit
- kind: code
  role: implementation
  target: app/main.py#_record_enrichment_genre_writes
---

# The owner’s pinned genres survive the vote

Genres recognized as manual Audiobookshelf choices are preserved after voting and conflict resolution, with their provenance shown. They are distinguished from matching-generated and enrichment-generated values: a genre the book’s own Audible listing carries, a foreign store category, a store name glued to more words, or scrap is never taken for the owner’s choice.
