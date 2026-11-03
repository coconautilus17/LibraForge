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
  - Metadata status
  - Companions
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
- entity: planned-move
  shows:
  - Source
  - Destination
  - Metadata
  - Review reasons
  - Companions
  - Result
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
- entity: metadata-match
  shows:
  - Book
  - Candidate
  - Provider
  - Score
  - Edit mode
  - Review reasons
  - Write outcome
entryPoints:
- web: /organizer
references:
- kind: code
  role: implementation
  target: app/main.py#start_organizer_run
---

# Folder Forge

Preview and apply book destinations and inspect move results.
