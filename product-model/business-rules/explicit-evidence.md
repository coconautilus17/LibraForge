---
appliesTo:
- type: entity
  id: enrichment-result
  facts:
  - Explicit choices
references:
- kind: code
  role: implementation
  target: app/explicit_evidence.py#book_explicit_evidence
- kind: code
  role: implementation
  target: app/enrichment_batch.py#apply_batch
---

# Only authoritative series ratings preselect explicit choices

HaremLit series ratings can preselect Explicit or Not explicit. Audible adult categories, Goodreads shelves and Open Library subjects are supporting evidence only; absence of evidence never proves a book clean. Harem genre alone is a review hint. Bulk explicit writes need the owner’s opt-in and an authoritative rating.
