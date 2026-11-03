---
kind: primary
routes:
  web: Web
steps:
- kind: condition
  unattended: true
  text: The current subject finishes after a stop request.
  entities: []
  contexts:
    web:
      place: web::whole-library
- kind: product
  text: The Product leaves the whole-library run Stopped with its saved results available for review or
    resumption.
  entities:
  - entity: whole-library-run
    effect: changes
    facts:
    - Progress
    - Results
    from: Stopping
    to: Stopped
  contexts:
    web:
      place: web::whole-library
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

# Retain a resumable pause

## Trigger

The current subject finishes after a stop request.

## Outcome

The Product leaves the whole-library run Stopped with its saved results available for review or resumption.
