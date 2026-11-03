---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner saves the abs-tract URL and Kindle region.
  entities: []
  contexts:
    web:
      place: web::goodreads
- kind: product
  text: The Product changes goodreads settings for subsequent searches without automatically enabling batch
    fallback.
  entities:
  - entity: goodreads-settings
    effect: changes
    facts:
    - URL
    - Kindle region
  contexts:
    web:
      place: web::goodreads
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#save_abs_tract_settings
---

# Save fallback service settings

## Trigger

The owner has an abs-tract service for Kindle covers.

## Outcome

The Product changes goodreads settings for subsequent searches without automatically enabling batch fallback.
