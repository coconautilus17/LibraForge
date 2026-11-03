---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner chooses Cancel.
  entities: []
  contexts:
    web:
      place: web::folder-forge
- kind: product
  text: The Product marks the run Cancelled and presents its final output when the process exits.
  entities:
  - entity: run
    effect: changes
    facts:
    - Progress
    - Results
    - Timing
    from: Running
    to: Cancelled
  contexts:
    web:
      place: web::folder-forge
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#cancel_run
- kind: code
  role: implementation
  target: app/main.py#get_draining
- kind: code
  role: implementation
  target: scripts/audible-metadata-fixer-v5.py#main
---

# Stop Folder Forge work

## Trigger

A Folder Forge job is in progress.

## Outcome

The Product marks the run Cancelled and presents its final output when the process exits.
