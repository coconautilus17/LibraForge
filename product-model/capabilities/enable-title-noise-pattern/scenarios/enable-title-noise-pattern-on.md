---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner switches the entry on.
  entities: []
  contexts:
    web:
      place: web::title-noise
- kind: product
  text: The Product changes the title noise pattern Enabled fact to true and saves immediately.
  entities:
  - entity: title-noise-pattern
    effect: changes
    facts:
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

# Enable a stored title noise pattern

## Trigger

The entry is disabled.

## Outcome

The Product changes the title noise pattern Enabled fact to true and saves immediately.
