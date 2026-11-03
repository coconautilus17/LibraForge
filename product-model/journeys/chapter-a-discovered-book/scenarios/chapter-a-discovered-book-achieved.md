---
kind: primary
result: achieved
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  capability: find-chapter-candidates
  text: The owner chooses Use this file for an audiobook candidate.
  entities:
  - entity: audiobook
    effect: reads
    facts:
    - Path
    - Audio
  contexts:
    web:
      place: web::chapter-forge
- kind: product
  actor: library-owner
  capability: load-chapters
  text: The Product loads the audiobook source and its chapter entries.
  entities:
  - entity: audiobook
    effect: reads
    facts:
    - Path
    - Audio
    - Identifiers
  - entity: chapter
    effect: reads
    facts:
    - Title
    - Timing
    - Evidence
    - Manual
  contexts:
    web:
      place: web::chapter-forge
- kind: actor
  actor: library-owner
  capability: detect-chapters
  text: The owner chooses Audible detection for the identified source.
  entities: []
  contexts:
    web:
      place: web::chapter-forge
- kind: product
  actor: library-owner
  capability: detect-chapters
  text: The Product creates chapter entries and saves audiobook artifacts.
  entities:
  - entity: chapter
    effect: creates
    facts:
    - Title
    - Timing
    - Evidence
    - Manual
  - entity: audiobook
    effect: changes
    facts:
    - Companions
  contexts:
    web:
      place: web::chapter-forge
references:
- kind: code
  role: implementation
  target: app/static/chapter-forge.js#findCandidate
- kind: code
  role: implementation
  target: app/main.py#run_audible_chapters_backend
---

# Chapter a discovered book successfully

## Trigger

The owner has searched for chapter candidates and picks one.

## Outcome

Detected chapters are saved for the chosen book.
