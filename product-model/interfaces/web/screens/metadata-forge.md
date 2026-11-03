---
entities:
- entity: audiobook
  shows:
  - Path
  - Title
  - Author
  - Narrator
  - Series
  - Identifiers
  - Genres
  - Audio
  - Metadata status
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
- entity: metadata-match
  shows:
  - Book
  - Candidate
  - Provider
  - Score
  - Edit mode
  - Review reasons
  - Write outcome
- entity: run
  shows:
  - Tool
  - Target
  - Options
  - Progress
  - Results
  - Timing
- entity: run-log
  shows:
  - Tool
  - Timing
  - Outcome
  - Output
- entity: series
  shows:
  - Name
  - Authors
  - Books
  - Shared metadata
entryPoints:
- web: /forge
references:
- kind: code
  role: implementation
  target: app/main.py#start_run
---

# Metadata Forge

Configure a batch match and inspect its results, review reasons and output.
