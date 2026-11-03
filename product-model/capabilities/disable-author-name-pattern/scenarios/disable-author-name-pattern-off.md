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
      place: web::author-names
- kind: product
  text: The Product changes the author name pattern Enabled fact to false and saves immediately.
  entities:
  - entity: author-name-pattern
    effect: changes
    facts:
    - Enabled
  contexts:
    web:
      place: web::author-names
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/author_names.py
- kind: code
  role: implementation
  target: app/static/pattern-settings.js
---

# Disable a stored author name pattern

## Trigger

An enabled entry should stop matching.

## Outcome

The Product changes the author name pattern Enabled fact to false and saves immediately.
