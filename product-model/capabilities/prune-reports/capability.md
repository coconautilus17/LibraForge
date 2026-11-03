---
availability:
- place: web
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
domain: reports
---

# Prune reports

Remove reports selected by either enabled retention limit, with their output and suspicion-review companions.
