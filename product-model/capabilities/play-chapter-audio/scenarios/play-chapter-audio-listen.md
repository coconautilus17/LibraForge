---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner plays the audio around a boundary or an evidence excerpt.
  entities: []
  contexts:
    web:
      place: web::chapter-forge
- kind: product
  text: The Product plays the corresponding audiobook interval and associates playback with the chapter evidence.
  entities:
  - entity: audiobook
    effect: reads
    facts:
    - Path
    - Audio
  - entity: chapter
    effect: reads
    facts:
    - Timing
    - Evidence
  contexts:
    web:
      place: web::chapter-forge
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#chaptering_audio_clip
- kind: code
  role: implementation
  target: app/static/chapter-forge.js#playRange
---

# Audition a chapter boundary

## Trigger

A chapter candidate is loaded.

## Outcome

The Product plays the corresponding audiobook interval and associates playback with the chapter evidence.
