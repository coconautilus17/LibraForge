---
availability:
- place: cli
references:
- kind: code
  role: implementation
  target: dev/benchmark/audit_check.py
domain: benchmark
---

# Carry the audit forward

Judge a tool's new run from the audit of its last one: keep the verdict of an unchanged result, settle a changed one by rule where the evidence is plain, and list the rest for hand review.
