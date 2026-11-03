---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner starts Whole library.
  entities: []
  contexts:
    web:
      place: web::whole-library
- kind: product
  text: The Product creates a Running whole-library run and Pending enrichment result entries for its subjects,
    saving progress after each compilation.
  entities:
  - entity: whole-library-run
    effect: creates
    facts:
    - Subjects
    - Progress
    - Timing
    - Results
    to: Running
  - entity: enrichment-result
    effect: creates
    facts:
    - Subject
    - Genres
    - Evidence
    - Pinned genres
    - Narrator
    - Explicit choices
    - Included books
    - Apply result
    to: Pending
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

# Start a library-wide compilation

## Trigger

Audiobookshelf is connected and no batch is compiling or applying.

## Outcome

The Product creates a Running whole-library run and Pending enrichment result entries for its subjects, saving progress after each compilation.
