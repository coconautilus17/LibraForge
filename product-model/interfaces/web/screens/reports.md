---
entities:
- entity: report-retention
  shows:
  - Age limit
  - Count limit
  collects:
  - Age limit
  - Count limit
- entity: run-log
  shows:
  - Tool
  - Timing
  - Outcome
  - Output
entryPoints:
- web: /settings#reports
references:
- kind: code
  role: implementation
  target: app/static/settings.html
---

# Report retention

Age and count limits for saved run reports, and pruning on demand.
