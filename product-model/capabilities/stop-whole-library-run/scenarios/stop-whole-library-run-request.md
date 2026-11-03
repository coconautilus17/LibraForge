---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner chooses Stop.
  entities: []
  contexts:
    web:
      place: web::whole-library
- kind: product
  text: The Product moves the whole-library run from Running to Stopping while the current subject can finish.
  entities:
  - entity: whole-library-run
    effect: changes
    facts:
    - Progress
    from: Running
    to: Stopping
  contexts:
    web:
      place: web::whole-library
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#enrichment_batch_stop
- kind: code
  role: implementation
  target: app/enrichment_batch.py#effective_status
- kind: code
  role: implementation
  target: app/enrichment_batch.py#run_batch
---

# Pause after the current subject

## Trigger

Compilation is active.

## Outcome

The Product moves the whole-library run from Running to Stopping while the current subject can finish.
