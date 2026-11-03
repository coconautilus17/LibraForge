---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner opens Patterns in use and Custom patterns.
  entities: []
  contexts:
    web:
      place: web::author-names
- kind: product
  text: The Product presents author name pattern facts, origin and enabled state.
  entities:
  - entity: author-name-pattern
    effect: reads
    facts:
    - Name
    - Spelling
    - Origin
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

# Inspect author name patterns

## Trigger

The owner opens Settings → Author names.

## Outcome

The Product presents author name pattern facts, origin and enabled state.
