---
references:
- kind: code
  role: implementation
  target: app/main.py#apply_series_group
- kind: code
  role: implementation
  target: app/enrichment.py#list_series_summary
- kind: code
  role: implementation
  target: scripts/review-libraforge-report.py
---

# Series

A named group of books whose shared metadata can be reviewed together.

## Information kept

- **Name** — Normalized series name.
- **Authors** — The author grouping used to distinguish same-named series.
- **Books** — Member book paths, titles and sequence numbers.
- **Shared metadata** — Proposed shared author, genre, narrator, language and explicit choices.
