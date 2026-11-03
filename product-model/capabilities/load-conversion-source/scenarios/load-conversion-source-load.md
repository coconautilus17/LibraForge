---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner loads the source folder or file.
  entities: []
  contexts:
    web:
      place: web::m4b-tool
- kind: product
  text: The Product presents the audiobook conversion metadata, audio compatibility and proposed M4B output
    path.
  entities:
  - entity: audiobook
    effect: reads
    facts:
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
  contexts:
    web:
      place: web::m4b-tool
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#load_m4b_metadata
- kind: code
  role: implementation
  target: app/static/m4b-tool.js#loadSidecar
---

# Prepare an M4B source

## Trigger

The owner selects a conversion candidate or path.

## Outcome

The Product presents the audiobook conversion metadata, audio compatibility and proposed M4B output path.
