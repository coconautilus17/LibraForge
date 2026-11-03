---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner watches a newly started job.
  entities: []
  contexts:
    web:
      place: web::metadata-forge
- kind: product
  text: The Product moves the run from Queued to Running and displays its processing phase.
  entities:
  - entity: run
    effect: changes
    facts:
    - Progress
    from: Queued
    to: Running
  contexts:
    web:
      place: web::metadata-forge
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#get_run
- kind: code
  role: implementation
  target: app/main.py#set_run_phase
---

# Observe work start

## Trigger

A newly accepted tool operation is queued.

## Outcome

The Product moves the run from Queued to Running and displays its processing phase.
