---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner saves the abs-agg URL.
  entities: []
  contexts:
    web:
      place: web::ga-sbt
- kind: product
  text: The Product saves the abs-agg URL for later manual searches and batch fallback.
  entities:
  - entity: ga-sbt-settings
    effect: changes
    facts:
    - URL
  contexts:
    web:
      place: web::ga-sbt
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#save_abs_agg_settings
- kind: code
  role: implementation
  target: app/static/settings.html
---

# Save the abs-agg address

## Trigger

The owner has an abs-agg service.

## Outcome

The Product saves the abs-agg URL for later manual searches and batch fallback.

## Edge cases

- A malformed service address is rejected.
