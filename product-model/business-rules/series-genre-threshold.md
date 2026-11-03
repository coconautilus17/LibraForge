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
  target: app/genre_voting.py#vote_unit
---

# Series genre support counts books that produced a vote

A series retains supported main genres at a threshold of one for fewer than four voting books, otherwise the ceiling of 25% of voting books. A book votes when it supports any main genre or subgenre; books without a vote do not dilute support. There is no fixed cap on supported main genres, and up to five subgenres are kept. Progression Fantasy is always a subgenre: a progression series with no other main genre is Fantasy. When Non-Fiction and a fiction genre both reach the threshold, Non-Fiction is kept only when it has more support than the strongest fiction genre, otherwise it is dropped. That conflict, a conflict settled within single books, and Young Adult beside Children’s are reported with each side’s book count and what was kept.
