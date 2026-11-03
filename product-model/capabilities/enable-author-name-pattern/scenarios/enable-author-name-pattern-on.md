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
      place: web::author-names
- kind: product
  text: The Product changes the author name pattern Enabled fact to true and saves immediately.
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

# Enable a stored author name pattern

## Trigger

The entry is disabled.

## Outcome

The Product changes the author name pattern Enabled fact to true and saves immediately.
