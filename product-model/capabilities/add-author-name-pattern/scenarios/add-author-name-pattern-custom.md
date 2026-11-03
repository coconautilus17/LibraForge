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
      place: web::author-names
- kind: product
  text: The Product creates the author name pattern as a custom enabled entry and applies it to subsequent
    matching.
  entities:
  - entity: author-name-pattern
    effect: creates
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

# Save a custom author name pattern

## Trigger

The shipped entries do not cover the desired case.

## Outcome

The Product creates the author name pattern as a custom enabled entry and applies it to subsequent matching.

## Edge cases

- A spelling exception must preserve the same letters and digits as the recognized name, and duplicate normalized names are rejected.
- A failed save reloads the persisted entries instead of leaving the rejected edit visible.
