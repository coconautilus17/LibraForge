---
entities:
- entity: series
  shows:
  - Name
  - Authors
  - Books
  - Shared metadata
- entity: enrichment-result
  shows:
  - Subject
  - Genres
  - Evidence
  - Pinned genres
  - Narrator
  - Explicit choices
  - Included books
  - Apply result
  collects:
  - Genres
  - Narrator
  - Explicit choices
  - Included books
- entity: audiobook
  shows:
  - Path
  - Title
  - Author
  - Narrator
  - Series
  - Genres
  - Explicit
entryPoints:
- web: /enrichment-forge
references:
- kind: code
  role: implementation
  target: app/main.py#enrichment_compile
---

# Enrichment Forge

Find a series or standalone book and curate its compiled evidence.
