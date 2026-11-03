---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner picks two detection methods and starts the comparison.
  entities: []
  contexts:
    web:
      place: web::chapter-forge
- kind: product
  text: The Product presents the two chapter sets and differences while preserving the saved chapter entries.
  entities:
  - entity: chapter
    effect: reads
    facts:
    - Title
    - Timing
    - Evidence
    - Manual
  - entity: run
    effect: creates
    facts:
    - Tool
    - Target
    - Options
    - Progress
    - Results
    - Timing
    to: Completed
  contexts:
    web:
      place: web::chapter-forge
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/static/chapter-forge.js#runMethodComparison
- kind: code
  role: implementation
  target: app/main.py#run_chaptering_worker
---

# Compare two detection methods

## Trigger

Both methods are configured.

## Outcome

The Product presents the two chapter sets and differences while preserving the saved chapter entries.
