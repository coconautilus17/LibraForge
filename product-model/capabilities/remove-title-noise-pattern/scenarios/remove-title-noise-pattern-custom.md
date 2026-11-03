---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner removes a custom entry.
  entities: []
  contexts:
    web:
      place: web::title-noise
- kind: product
  text: The Product removes the title noise pattern and saves the remaining list.
  entities:
  - entity: title-noise-pattern
    effect: removes
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

# Remove a custom title noise pattern

## Trigger

A custom entry is no longer wanted.

## Outcome

The Product removes the title noise pattern and saves the remaining list.
