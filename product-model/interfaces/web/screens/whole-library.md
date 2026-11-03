---
entities:
- entity: whole-library-run
  shows:
  - Subjects
  - Progress
  - Timing
  - Results
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
entryPoints:
- web: /enrichment-forge
references:
- kind: code
  role: implementation
  target: app/main.py#enrichment_batch_status
---

# Whole library

Compile and review enrichment across the library.
