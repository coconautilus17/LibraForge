---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner switches the entry off.
  entities: []
  contexts:
    web:
      place: web::title-noise
- kind: product
  text: The Product changes the title noise pattern Enabled fact to false and saves immediately.
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

# Disable a stored title noise pattern

## Trigger

An enabled entry should stop matching.

## Outcome

The Product changes the title noise pattern Enabled fact to false and saves immediately.
