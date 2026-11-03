---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner chooses Resume.
  entities: []
  contexts:
    web:
      place: web::whole-library
- kind: product
  text: The Product returns the whole-library run to Running and compiles subjects still due, retaining applied
    enrichment result entries.
  entities:
  - entity: whole-library-run
    effect: changes
    facts:
    - Progress
    - Results
    from: Stopped
    to: Running
  - entity: enrichment-result
    effect: reads
    facts:
    - Subject
    - Genres
    - Evidence
    - Pinned genres
    - Narrator
    - Explicit choices
    - Included books
    - Apply result
  contexts:
    web:
      place: web::whole-library
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/enrichment_batch.py#_needs_compile
- kind: code
  role: implementation
  target: app/enrichment_batch.py#effective_status
- kind: code
  role: implementation
  target: app/main.py#enrichment_batch_start
---

# Continue saved compilation

## Trigger

The batch was stopped or interrupted by a restart.

## Outcome

The Product returns the whole-library run to Running and compiles subjects still due, retaining applied enrichment result entries.

## Edge cases

- A Compiled result with degraded sources is due for recompilation; Applied and Apply failed results are not recompiled automatically.
