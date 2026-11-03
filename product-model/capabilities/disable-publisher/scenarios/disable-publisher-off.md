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
      place: web::publishers
- kind: product
  text: The Product changes the publisher Enabled fact to false and saves immediately.
  entities:
  - entity: publisher
    effect: changes
    facts:
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

# Disable a stored publisher

## Trigger

An enabled entry should stop matching.

## Outcome

The Product changes the publisher Enabled fact to false and saves immediately.
