---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner downloads the JSON report or the output log.
  entities: []
  contexts:
    web:
      place: web::metadata-forge
- kind: product
  text: The Product returns the selected run log or structured result for local inspection.
  entities:
  - entity: run-log
    effect: reads
    facts:
    - Tool
    - Timing
    - Outcome
    - Output
  contexts:
    web:
      place: web::metadata-forge
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#download
- kind: code
  role: implementation
  target: app/static/ui-common.js
---

# Save Metadata Forge evidence

## Trigger

A completed run has report artifacts.

## Outcome

The Product returns the selected run log or structured result for local inspection.

## Edge cases

- An artifact that is absent or already pruned is reported unavailable.
