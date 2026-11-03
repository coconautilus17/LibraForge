---
kind: alternate
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner chooses Hybrid and starts detection with the selected speech settings.
  entities: []
  contexts:
    web:
      place: web::chapter-forge
- kind: product
  text: The Product creates chapter candidates from silence and transcript evidence, applies available optional
    language-model corrections, saves audiobook artifacts and completes the run.
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
  - entity: run
    effect: creates
    facts:
    - Tool
    - Target
    - Options
    - Progress
    - Results
    - Timing
    to: Completed
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

# Detect from silence and speech

## Trigger

The speech-recognition runtime is installed and the configured ASR server is reachable.

## Outcome

The Product creates chapter candidates from silence and transcript evidence, applies available optional language-model corrections, saves audiobook artifacts and completes the run.

## Edge cases

- Optional language-model corrections become part of the saved chapter proposal; the supporting review and unresolved issues remain available.
- The owner can inspect detected labels and timings before using them in conversion.
