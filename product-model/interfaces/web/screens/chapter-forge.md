---
entities:
- entity: audiobook
  shows:
  - Path
  - Audio
  - Identifiers
  - Companions
- entity: chapter
  shows:
  - Title
  - Timing
  - Evidence
  - Manual
  collects:
  - Title
  - Timing
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
- web: /chapter-forge
references:
- kind: code
  role: implementation
  target: app/main.py#load_chaptering
---

# Chapter Forge

Detect and curate chapter boundaries with audio and transcript evidence.
