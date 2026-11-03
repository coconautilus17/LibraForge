---
kind: primary
routes:
  web: Web
steps:
- kind: condition
  unattended: true
  text: A completed processing operation has saved its report.
  entities: []
  contexts:
    web:
      place: web::reports
- kind: product
  text: The Product removes run log history selected by the enabled retention limits.
  entities:
  - entity: run-log
    effect: removes
  contexts:
    web:
      place: web::reports
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

# Prune after a completed report

## Trigger

A completed run has saved its report.

## Outcome

The Product removes run log history selected by the enabled retention limits.
