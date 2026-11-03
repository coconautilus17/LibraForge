---
kind: edge
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner starts detection with a speech-recognition method.
  entities: []
  contexts:
    web:
      place: web::chapter-forge
- kind: product
  text: The Product marks the run Failed with the dependency error instead of presenting successful detection.
  entities:
  - entity: run
    effect: creates
    facts:
    - Tool
    - Target
    - Options
    - Progress
    - Results
    - Timing
    to: Failed
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

# Explain a missing detection dependency

## Trigger

The speech-recognition runtime is missing, or Hybrid cannot reach the configured ASR server.

## Outcome

The Product marks the run Failed with the dependency error instead of presenting successful detection.
