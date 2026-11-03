---
kind: alternate
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner chooses No conversion and starts the merge.
  entities: []
  contexts:
    web:
      place: web::m4b-tool
- kind: product
  text: The Product creates an audiobook M4B using stream-copy and applies the selected metadata.
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
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#build_m4b_command
- kind: code
  role: implementation
  target: app/main.py#resolve_m4b_input_files
- kind: code
  role: implementation
  target: app/main.py#run_m4b_worker
---

# Merge compatible AAC streams

## Trigger

All source streams are AAC with matching sample rate and channel layout.

## Outcome

The Product creates an audiobook M4B using stream-copy and applies the selected metadata.

## Edge cases

- Different bitrates alone do not rule out stream-copy.
