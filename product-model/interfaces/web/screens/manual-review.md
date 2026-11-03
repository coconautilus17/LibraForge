---
entities:
- entity: audiobook
  shows:
  - Path
  - Title
  - Author
  - Narrator
  - Series
  - Publication
  - Identifiers
  - Genres
  - Explicit
  - Summary
  - Cover
  - Audio
  - Metadata status
  - Original metadata
  collects:
  - Path
  - Title
  - Author
  - Narrator
  - Series
  - Publication
  - Identifiers
  - Genres
  - Explicit
  - Summary
  - Cover
- entity: ebook
  shows:
  - Path
  - Title
  - Author
  - Series
  - Publication
  - Genres
  - Summary
  - Cover
  - Metadata status
  collects:
  - Path
  - Title
  - Author
  - Series
  - Publication
  - Genres
  - Summary
  - Cover
- entity: metadata-match
  shows:
  - Book
  - Candidate
  - Provider
  - Score
  - Edit mode
  - Review reasons
  - Write outcome
- entity: series
  shows:
  - Name
  - Authors
  - Books
  - Shared metadata
entryPoints:
- web: /forge#manual-review
references:
- kind: code
  role: implementation
  target: app/main.py#inspect_manual_review_target
---

# Manual Review

Find one local book, compare candidates and curate its metadata.
