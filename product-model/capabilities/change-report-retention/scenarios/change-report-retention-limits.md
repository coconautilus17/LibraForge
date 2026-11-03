---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner sets the age and count limits and chooses Save.
  entities: []
  contexts:
    web:
      place: web::reports
- kind: product
  text: The Product changes retention settings and applies the selected pruning policy through the settings
    workflow.
  entities:
  - entity: report-retention
    effect: changes
    facts:
    - Age limit
    - Count limit
  contexts:
    web:
      place: web::reports
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#save_retention_settings
- kind: code
  role: implementation
  target: app/static/settings.html
---

# Save retention limits

## Trigger

The owner wants to limit saved report history.

## Outcome

The Product changes retention settings and applies the selected pruning policy through the settings workflow.

## Edge cases

- Enabled limits use at least one day or one report.
