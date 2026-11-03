---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner chooses Prune now.
  entities: []
  contexts:
    web:
      place: web::reports
- kind: product
  text: The Product removes selected run log history and returns the deletion count.
  entities:
  - entity: run-log
    effect: removes
  contexts:
    web:
      place: web::reports
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#_prune_reports
- kind: code
  role: implementation
  target: app/main.py#prune_reports_now
- kind: code
  role: implementation
  target: app/main.py#write_final_report
---

# Prune report history

## Trigger

Retention limits are configured.

## Outcome

The Product removes selected run log history and returns the deletion count.

## Edge cases

- With both limits disabled no report is selected.
