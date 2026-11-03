---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner acknowledges the author-name upgrade notice.
  entities: []
  contexts:
    web:
      place: web::author-names
- kind: product
  text: The Product clears the author name settings Notice pending fact without changing the scheme.
  entities:
  - entity: author-name-settings
    effect: changes
    facts:
    - Notice pending
  contexts:
    web:
      place: web::author-names
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#acknowledge_author_notice
---

# Acknowledge the upgrade notice

## Trigger

An upgraded installation has a pending notice.

## Outcome

The Product clears the author name settings Notice pending fact without changing the scheme.
