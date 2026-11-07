---
appliesTo:
- type: entity
  id: benchmark
references:
- kind: code
  role: implementation
  target: dev/benchmark/bench_data.py#Benchmark
- kind: code
  role: implementation
  target: dev/benchmark/manifest.example.json
---

# Every step after the runs reads the same benchmark

The audit, its checks, the second audit, the hidden-books count, carrying the audit forward and the page all read
the dataset, the runs and the audit the manifest names, and each tool's result through one statement of how it
writes. None names a file of its own.

## Rationale

A benchmark is only comparable when every number on the page comes from the same files.
