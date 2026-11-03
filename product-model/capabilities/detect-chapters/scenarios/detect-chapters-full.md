---
kind: alternate
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner chooses Full transcription and starts detection.
  entities: []
  contexts:
    web:
      place: web::chapter-forge
- kind: product
  text: The Product creates chapter candidates from transcribed speech, including optional gap rescans and
    silence alignment, and saves audiobook artifacts.
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
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#run_chaptering_worker
- kind: code
  role: implementation
  target: app/main.py#run_audible_chapters_backend
- kind: code
  role: implementation
  target: app/chaptering.py
---

# Detect from full transcription

## Trigger

The speech-recognition runtime is installed.

## Outcome

The Product creates chapter candidates from transcribed speech, including optional gap rescans and silence alignment, and saves audiobook artifacts.
