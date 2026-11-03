---
kind: validation
routes:
  web: Web
  cli: Command line
steps:
- kind: actor
  actor: library-owner
  text: The owner starts a preview of a folder the fixer has not processed.
  entities: []
  contexts:
    web:
      place: web::folder-forge
    cli:
      place: cli
- kind: product
  text: The Product completes the run with the no-sidecars notice before creating moves; the owner may acknowledge
    and rerun.
  entities:
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
  target: scripts/organize-audiobooks-by-metadata-v3_13.py#infer_metadata
- kind: code
  role: implementation
  target: app/main.py#build_organizer_command
---

# Require a decision when metadata companions are absent

## Trigger

Scanned items contain no fixer metadata companions.

## Outcome

The Product completes the run with the no-sidecars notice before creating moves; the owner may acknowledge and rerun.
