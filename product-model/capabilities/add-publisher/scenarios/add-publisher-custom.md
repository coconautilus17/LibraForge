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
      place: web::publishers
- kind: product
  text: The Product creates the publisher as a custom enabled entry and applies it to subsequent matching.
  entities:
  - entity: publisher
    effect: creates
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

# Save a custom publisher

## Trigger

The shipped entries do not cover the desired case.

## Outcome

The Product creates the publisher as a custom enabled entry and applies it to subsequent matching.

## Edge cases

- A publisher needs a name and a recognized special provider when one is selected.
- A failed save reloads the persisted entries instead of leaving the rejected edit visible.
