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
      place: web::m4b-tool
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
      place: web::m4b-tool
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

# Stop M4B Tool work

## Trigger

An M4B Tool conversion is in progress.

## Outcome

The Product marks the run Cancelled and presents its final output when the process exits.
