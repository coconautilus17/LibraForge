---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner opens the review table and filters it.
  entities: []
  contexts:
    web:
      place: web::whole-library
- kind: product
  text: The Product presents the enrichment result rows and whole-library run progress; Edit carries the chosen
    subject into its detailed compilation and curation.
  entities:
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
  - entity: whole-library-run
    effect: reads
    facts:
    - Subjects
    - Progress
    - Timing
    - Results
  contexts:
    web:
      place: web::whole-library
  actor: library-owner
- kind: product
  actor: library-owner
  text: The Product carries the selected enrichment result into detailed curation.
  entities:
  - entity: enrichment-result
    effect: reads
    facts:
    - Subject
  contexts:
    web:
      place: web::enrichment-forge
references:
- kind: code
  role: implementation
  target: app/main.py#enrichment_batch_status
- kind: code
  role: implementation
  target: app/static/enrichment-forge.js#renderBatchTable
---

# Inspect the review table

## Trigger

A whole-library run has saved results.

## Outcome

The Product presents the enrichment result rows and whole-library run progress; Edit carries the chosen subject into its detailed compilation and curation.

## Edge cases

- A row whose sources disagree is listed under Needs review, marked with the conflict, and starts unticked.
