---
kind: edge
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner starts the conversion.
  entities: []
  contexts:
    web:
      place: web::m4b-tool
- kind: product
  text: The Product marks the run Failed and preserves its error and output for review.
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
    to: Failed
  contexts:
    web:
      place: web::m4b-tool
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#build_m4b_command
- kind: code
  role: implementation
  target: app/main.py#resolve_m4b_input_files
- kind: code
  role: implementation
  target: app/main.py#run_m4b_worker
---

# Report conversion failure

## Trigger

The conversion process or final tagging fails.

## Outcome

The Product marks the run Failed and preserves its error and output for review.
