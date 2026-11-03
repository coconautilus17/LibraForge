---
kind: edge
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner starts Hybrid detection with language-model review on.
  entities: []
  contexts:
    web:
      place: web::chapter-forge
- kind: product
  text: The Product creates chapter candidates without AI corrections, saves audiobook artifacts and completes
    the run with an unavailable-review diagnostic.
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

# Surface chapter-name review failure

## Trigger

Hybrid detection requested language-model review and that dependency fails.

## Outcome

The Product creates chapter candidates without AI corrections, saves audiobook artifacts and completes the run with an unavailable-review diagnostic.
