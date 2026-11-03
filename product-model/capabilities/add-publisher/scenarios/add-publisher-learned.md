---
kind: alternate
routes:
  web: Web
steps:
- kind: condition
  unattended: true
  text: Background matching has discovered a new imprint distinct from the author and narrator credits.
  entities: []
  contexts:
    web:
      place: web::publishers
- kind: product
  text: The Product creates a publisher entry with learned origin for later settings review.
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
references:
- kind: code
  role: implementation
  target: app/publisher_policy.py
- kind: code
  role: implementation
  target: app/static/pattern-settings.js
---

# Learn an unseen publisher

## Trigger

A matching run observes a previously unknown publisher distinct from the authors and narrators.

## Outcome

The Product creates a publisher entry with learned origin for later settings review.
