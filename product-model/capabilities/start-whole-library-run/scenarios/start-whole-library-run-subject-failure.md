---
kind: edge
routes:
  web: Web
steps:
- kind: condition
  unattended: true
  text: A scheduled subject cannot compile.
  entities: []
  contexts:
    web:
      place: web::whole-library
- kind: product
  text: The Product marks the Pending enrichment result Failed and keeps the whole-library run progressing
    through the remaining subjects.
  entities:
  - entity: enrichment-result
    effect: changes
    facts:
    - Evidence
    - Apply result
    from: Pending
    to: Failed
  - entity: whole-library-run
    effect: changes
    facts:
    - Progress
    - Results
  contexts:
    web:
      place: web::whole-library
references:
- kind: code
  role: implementation
  target: app/main.py#enrichment_batch_start
- kind: code
  role: implementation
  target: app/enrichment_batch.py#run_batch
- kind: code
  role: implementation
  target: app/static/enrichment-forge.js#startBatch
---

# Record a failed subject

## Trigger

A scheduled subject cannot compile.

## Outcome

The Product marks the Pending enrichment result Failed and keeps the whole-library run progressing through the remaining subjects.
