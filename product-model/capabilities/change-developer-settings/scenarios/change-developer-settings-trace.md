---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner switches debug tracing and sets an optional log path.
  entities: []
  contexts:
    web:
      place: web::developer
- kind: product
  text: The Product changes developer preferences for subsequent metadata processing.
  entities:
  - entity: developer-preferences
    effect: changes
    facts:
    - Debug tracing
    - Trace destination
  contexts:
    web:
      place: web::developer
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/static/ui-preferences.js
- kind: code
  role: implementation
  target: app/debug_trace.py
- kind: code
  role: implementation
  target: app/main.py#build_command
---

# Configure debug evidence

## Trigger

The owner wants diagnostic output for a later run.

## Outcome

The Product changes developer preferences for subsequent metadata processing.
