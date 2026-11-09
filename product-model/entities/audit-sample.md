---
domain: benchmark
references:
- kind: code
  role: implementation
  target: dev/benchmark/reaudit_sample.py
---

# Audit sample

Benchmark books drawn at random to audit a second time, which measures how often the audit is wrong.

## Information kept

- **Books** — The books drawn.
- **Seed** — The random seed that draws them again.
- **Findings** — Each verdict the second audit found wrong, and whether a checking rule or one hand verdict caused it.
