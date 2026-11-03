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
      place: web::metadata-forge
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
      place: web::metadata-forge
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

# Stop Metadata Forge work

## Trigger

A Metadata Forge job is in progress.

## Outcome

The Product marks the run Cancelled and presents its final output when the process exits.

## Edge cases

- Cancellation of metadata writes can continue to show draining workers before the same target becomes available again.
