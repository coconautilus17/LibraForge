---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner opens the latest output log.
  entities: []
  contexts:
    web:
      place: web::folder-forge
- kind: product
  text: The Product presents the run log with mode, metrics and reported issues.
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
      place: web::folder-forge
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#get_latest_run_log
- kind: code
  role: implementation
  target: app/static/ui-common.js
---

# Read Folder Forge output

## Trigger

Folder Forge has finished a job.

## Outcome

The Product presents the run log with mode, metrics and reported issues.
