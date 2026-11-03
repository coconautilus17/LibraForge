---
availability:
- place: web
references:
- kind: code
  role: implementation
  target: app/enrichment.py#list_series_summary
- kind: code
  role: implementation
  target: app/enrichment.py#split_group_by_author
- kind: code
  role: implementation
  target: app/main.py#enrichment_series
domain: enrichment-forge
---

# Browse series

Find series and standalone books already indexed by Audiobookshelf, grouping normalized variants and separating unrelated authors.
