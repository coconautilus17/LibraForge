---
singleton: true
domain: reports
references:
- kind: code
  role: implementation
  target: app/main.py#save_retention_settings
- kind: code
  role: implementation
  target: app/main.py#_prune_reports
---

# Report retention

The installation’s optional report age and count limits.

## Information kept

- **Age limit** — Whether an age limit applies and how many days to retain.
- **Count limit** — Whether a count limit applies and how many newest reports to retain.
