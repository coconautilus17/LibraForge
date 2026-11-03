---
appliesTo:
- type: entity
  id: run-log
references:
- kind: code
  role: implementation
  target: app/main.py#write_final_report
---

# Tool runs record their output and results

Web tool runs record timing, progress output, terminal outcome and per-book results in the run log. Retention can remove old reports and their companion output.
