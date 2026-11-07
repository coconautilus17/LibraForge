---
entities:
- entity: benchmark
  shows:
  - Runs
  - LibraForge build
  - Hidden books
- entity: audit-verdict
  shows:
  - Final verdict
  - Field problems
- entity: audit-sample
  shows:
  - Findings
entryPoints:
- benchmark-page: https://coconautilus17.github.io/LibraForge/#glance
references:
- kind: code
  role: implementation
  target: dev/benchmark/report.py#glance
- kind: code
  role: implementation
  target: dev/benchmark/report.py#numbers_table
- kind: code
  role: implementation
  target: dev/benchmark/report.py#tool_cards
- kind: code
  role: implementation
  target: dev/benchmark/report.py#lf_findings
---

# Results

What each tool left on the whole library, how each tool matches and writes, where LibraForge went wrong, and
how the results were judged.
