---
availability:
- place: cli
references:
- kind: code
  role: implementation
  target: dev/benchmark/reaudit_run.py
domain: benchmark
---

# Carry the audit forward

Judge a new LibraForge run from the audit of the last one: keep the verdict of an unchanged result, settle a changed one by rule where the evidence is plain, and list the rest for hand review.
