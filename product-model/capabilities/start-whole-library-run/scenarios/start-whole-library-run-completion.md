---
kind: primary
routes:
  web: Web
steps:
- kind: condition
  unattended: true
  text: The background compilation reaches its remaining subjects.
  entities: []
  contexts:
    web:
      place: web::whole-library
- kind: product
  text: The Product changes each Pending enrichment result to Compiled and leaves the whole-library run
    Done after all due subjects are attempted.
  entities:
  - entity: enrichment-result
    effect: changes
    facts:
    - Subject
    - Genres
    - Evidence
    - Pinned genres
    - Narrator
    - Explicit choices
    - Included books
    - Apply result
    from: Pending
    to: Compiled
  - entity: whole-library-run
    effect: changes
    facts:
    - Subjects
    - Progress
    - Timing
    - Results
    from: Running
    to: Done
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

# Finish sequential compilation

## Trigger

The background compilation reaches its remaining subjects.

## Outcome

The Product changes each Pending enrichment result to Compiled and leaves the whole-library run Done after all due subjects are attempted.
