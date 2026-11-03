---
kind: edge
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner starts detection with the resource guard on.
  entities: []
  contexts:
    web:
      place: web::chapter-forge
- kind: product
  text: The Product stops the run and presents the resource guard reason.
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
    to: Cancelled
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

# Stop detection under resource pressure

## Trigger

Resource guard detects sustained configured memory, swap or CPU pressure.

## Outcome

The Product stops the run and presents the resource guard reason.
