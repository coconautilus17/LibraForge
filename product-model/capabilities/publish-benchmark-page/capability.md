---
availability:
- place: cli
references:
- kind: code
  role: implementation
  target: dev/benchmark/publish_pages.sh
- kind: code
  role: implementation
  target: dev/benchmark/report.py
domain: benchmark
---

# Publish the benchmark page

Build the comparison page and its downloads from the benchmark and commit them to the published branch, listing only the tags a matcher reads.
