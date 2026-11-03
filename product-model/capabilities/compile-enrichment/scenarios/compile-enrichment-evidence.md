---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner compiles the selected series.
  entities:
  - entity: series
    effect: reads
    facts:
    - Name
    - Authors
    - Books
    - Shared metadata
  contexts:
    web:
      place: web::enrichment-forge
- kind: product
  text: The Product reads series members and audiobook metadata and creates a Compiled enrichment result with
    ranked genre evidence, pinned genres, source status and per-book explicit suggestions.
  entities:
  - entity: series
    effect: reads
    facts:
    - Name
    - Authors
    - Books
    - Shared metadata
  - entity: audiobook
    effect: reads
    facts:
    - Path
    - Title
    - Author
    - Narrator
    - Series
    - Genres
    - Explicit
  - entity: enrichment-result
    effect: creates
    facts:
    - Subject
    - Genres
    - Evidence
    - Pinned genres
    - Narrator
    - Explicit choices
    - Included books
    - Apply result
    to: Compiled
  contexts:
    web:
      place: web::enrichment-forge
  actor: library-owner
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
---

# Compile a series proposal

## Trigger

The owner selects an indexed series.

## Outcome

The Product reads series members and audiobook metadata and creates a Compiled enrichment result with ranked genre evidence, pinned genres, source status and per-book explicit suggestions.

## Edge cases

- Items without audio do not contribute source searches or votes and start excluded.
- Narrators are listed as evidence, while the shared narrator input begins empty.
- Only an authoritative HaremLit rating preselects an explicit choice; other positive signals remain evidence.
- A book without an ASIN, or whose ASIN Audible no longer lists, is searched by title and author; Metadata Forge’s own pick at its minimum score chooses the result, and when none qualifies the first result by the book’s author is used. Another author’s book never counts.
- Genres that exclude each other but both reached the vote are shown as a Sources disagree notice with each side’s book count and the genres kept.
