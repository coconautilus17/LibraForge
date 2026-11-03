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
      place: web::publishers
- kind: product
  text: The Product changes the publisher Enabled fact to true and saves immediately.
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

# Enable a stored publisher

## Trigger

The entry is disabled.

## Outcome

The Product changes the publisher Enabled fact to true and saves immediately.
