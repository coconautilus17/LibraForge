---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner watches the progress panel.
  entities: []
  contexts:
    web:
      place: web::folder-forge
- kind: product
  text: The Product presents the run’s phase, counts, current target and results, using its saved report after
    processing ends.
  entities:
  - entity: run
    effect: reads
    facts:
    - Tool
    - Target
    - Options
    - Progress
    - Results
    - Timing
  contexts:
    web:
      place: web::folder-forge
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#get_run
- kind: code
  role: implementation
  target: app/main.py#set_run_phase
---

# Observe Folder Forge progress

## Trigger

A Folder Forge job has started.

## Outcome

The Product presents the run’s phase, counts, current target and results, using its saved report after processing ends.
