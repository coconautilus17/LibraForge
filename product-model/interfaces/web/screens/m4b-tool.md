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
  - Summary
  - Cover
  - Audio
  - Conversion metadata
  collects:
  - Conversion metadata
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
entryPoints:
- web: /m4b-tool
references:
- kind: code
  role: implementation
  target: app/main.py#load_m4b_metadata
---

# M4B Tool

Discover sources, inspect audio compatibility and prepare a merged M4B.
