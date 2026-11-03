---
kind: primary
result: achieved
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  capability: discover-conversion-sources
  text: The owner chooses Load this book on an audiobook conversion candidate.
  entities:
  - entity: audiobook
    effect: reads
    facts:
    - Path
    - Audio
  contexts:
    web:
      place: web::m4b-tool
- kind: product
  actor: library-owner
  capability: load-conversion-source
  text: The Product loads the audiobook source metadata and output proposal.
  entities:
  - entity: audiobook
    effect: reads
    facts:
    - Conversion metadata
    - Audio
    - Path
  contexts:
    web:
      place: web::m4b-tool
- kind: actor
  actor: library-owner
  capability: convert-audiobook
  text: The owner starts conversion with reviewed output settings.
  entities: []
  contexts:
    web:
      place: web::m4b-tool
- kind: product
  actor: library-owner
  capability: convert-audiobook
  text: The Product creates the resulting audiobook M4B.
  entities:
  - entity: audiobook
    effect: creates
    facts:
    - Path
    - Title
    - Author
    - Narrator
    - Series
    - Publication
    - Identifiers
    - Genres
    - Summary
    - Cover
    - Audio
  contexts:
    web:
      place: web::m4b-tool
references:
- kind: code
  role: implementation
  target: app/static/m4b-tool.js#renderDiscoveryResults
- kind: code
  role: implementation
  target: app/main.py#run_m4b_worker
---

# Convert a discovered book successfully

## Trigger

Discovery lists a multipart or non-M4B book the owner wants merged.

## Outcome

The selected source has produced a merged M4B.
