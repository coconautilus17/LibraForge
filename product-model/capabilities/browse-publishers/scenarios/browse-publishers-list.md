---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner opens Patterns in use and Custom patterns.
  entities: []
  contexts:
    web:
      place: web::publishers
- kind: product
  text: The Product presents publisher facts, origin and enabled state.
  entities:
  - entity: publisher
    effect: reads
    facts:
    - Name
    - Special provider
    - Origin
    - Enabled
  contexts:
    web:
      place: web::publishers
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/publisher_policy.py
- kind: code
  role: implementation
  target: app/static/pattern-settings.js
---

# Inspect publishers

## Trigger

The owner opens Settings → Publishers.

## Outcome

The Product presents publisher facts, origin and enabled state.
