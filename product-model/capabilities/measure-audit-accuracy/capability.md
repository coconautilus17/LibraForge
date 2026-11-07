---
availability:
- place: cli
references:
- kind: code
  role: implementation
  target: dev/benchmark/reaudit_sample.py
- kind: code
  role: implementation
  target: dev/benchmark/audit_check.py#tally_findings
domain: benchmark
---

# Measure audit accuracy

Audit a random sample of books a second time, and a fresh sample after the fixes, to measure how often a verdict is wrong; the page states both rates.
