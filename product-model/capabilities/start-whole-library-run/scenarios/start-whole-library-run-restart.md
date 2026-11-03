---
kind: alternate
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner confirms Start over.
  entities: []
  contexts:
    web:
      place: web::whole-library
- kind: product
  text: The Product resets the whole-library run’s subjects and results and starts compilation again without
    changing audiobook metadata.
  entities:
  - entity: whole-library-run
    effect: changes
    facts:
    - Subjects
    - Progress
    - Timing
    - Results
  - entity: audiobook
    effect: reads
    facts:
    - Genres
    - Narrator
    - Explicit
  contexts:
    web:
      place: web::whole-library
  actor: library-owner
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

# Start over with new proposals

## Trigger

An earlier batch has saved results.

## Outcome

The Product resets the whole-library run’s subjects and results and starts compilation again without changing audiobook metadata.
