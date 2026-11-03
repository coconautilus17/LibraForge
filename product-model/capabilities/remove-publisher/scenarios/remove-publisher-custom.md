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
      place: web::publishers
- kind: product
  text: The Product removes the publisher and saves the remaining list.
  entities:
  - entity: publisher
    effect: removes
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

# Remove a custom publisher

## Trigger

A custom entry is no longer wanted.

## Outcome

The Product removes the publisher and saves the remaining list.
