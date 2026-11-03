---
kind: edge
routes:
  web: Web
  cli: Command line
steps:
- kind: actor
  actor: library-owner
  text: The owner starts Folder Forge with Apply on.
  entities: []
  contexts:
    web:
      place: web::folder-forge
    cli:
      place: cli
- kind: product
  text: The Product marks the affected planned move Failed with its error and continues other moves, reporting
    succeeded and failed totals.
  entities:
  - entity: planned-move
    effect: changes
    facts:
    - Result
    from: Planned
    to: Failed
  contexts:
    web:
      place: web::folder-forge
    cli:
      place: cli
  actor: library-owner
references:
- kind: code
  role: implementation
  target: scripts/organize-audiobooks-by-metadata-v3_13.py#main
- kind: code
  role: implementation
  target: scripts/organize-audiobooks-by-metadata-v3_13.py#execute_planned_move
- kind: code
  role: implementation
  target: app/static/organizer.js#showOrgApplyConfirm
---

# Isolate a failed move

## Trigger

A source disappears or a relocation encounters a filesystem error.

## Outcome

The Product marks the affected planned move Failed with its error and continues other moves, reporting succeeded and failed totals.
