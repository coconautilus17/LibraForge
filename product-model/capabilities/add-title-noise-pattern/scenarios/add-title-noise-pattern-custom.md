---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner fills in a custom entry and chooses Add.
  entities: []
  contexts:
    web:
      place: web::title-noise
- kind: product
  text: The Product creates the title noise pattern as a custom enabled entry and applies it to subsequent
    matching.
  entities:
  - entity: title-noise-pattern
    effect: creates
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

# Save a custom title noise pattern

## Trigger

The shipped entries do not cover the desired case.

## Outcome

The Product creates the title noise pattern as a custom enabled entry and applies it to subsequent matching.

## Edge cases

- A noise phrase must be nonempty and at most 500 characters; common separators are tolerated when matching.
- A failed save reloads the persisted entries instead of leaving the rejected edit visible.
