---
appliesTo:
- type: entity
  id: report-retention
references:
- kind: code
  role: implementation
  target: app/main.py#_prune_reports
---

# Either enabled retention limit can select a report for removal

Age selection uses the report’s modification time; count selection keeps the newest report names. The union is pruned with matching output and suspicion-review artifacts. Both limits disabled retains history.
