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
      place: web::title-noise
- kind: product
  text: The Product presents title noise pattern facts, origin and enabled state.
  entities:
  - entity: title-noise-pattern
    effect: reads
    facts:
    - Label
    - Pattern
    - Origin
    - Enabled
  contexts:
    web:
      place: web::title-noise
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/title_noise_policy.py
- kind: code
  role: implementation
  target: app/static/pattern-settings.js
---

# Inspect title noise patterns

## Trigger

The owner opens Settings → Title noise.

## Outcome

The Product presents title noise pattern facts, origin and enabled state.
