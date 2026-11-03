---
appliesTo:
- type: entity
  id: enrichment-result
  facts:
  - Genres
  - Evidence
references:
- kind: code
  role: implementation
  target: app/genre_voting.py#book_vote
- kind: code
  role: implementation
  target: app/enrichment.py#build_book_voters
- kind: code
  role: implementation
  target: app/enrichment.py#enrichment_written_genres
---

# Genre votes distinguish editorial and crowd evidence

Audible categories, description keywords and eligible embedded file genres have weight two. AudioSilo, Goodreads, Open Library and existing unpinned Audiobookshelf genres have weight one. A book’s main genre normally needs weight two; when only crowd evidence answers, up to two tied broad genres may supply a fallback, excluding strong specialty genres. File genres written by Metadata Forge do not count again as independent editorial evidence, and genres Enrichment Forge itself wrote earlier, other than the owner’s pinned ones, do not vote again. When one source names both Non-Fiction and a fiction genre or a children’s or teen audience, the side with more of that source’s labels wins and an even count keeps both. When a book’s sources still disagree, the side with more evidence weight wins for that book and a tie is left to the series vote. Classics, Humor and Audio Drama belong to neither side.
