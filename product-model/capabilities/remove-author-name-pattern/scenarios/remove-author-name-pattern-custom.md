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
      place: web::author-names
- kind: product
  text: The Product removes the author name pattern and saves the remaining list.
  entities:
  - entity: author-name-pattern
    effect: removes
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

# Remove a custom author name pattern

## Trigger

A custom entry is no longer wanted.

## Outcome

The Product removes the author name pattern and saves the remaining list.
