---
availability:
- place: cli
references:
- kind: code
  role: implementation
  target: dev/benchmark/collect.py#collect
- kind: code
  role: implementation
  target: dev/benchmark/collect.py#main
domain: benchmark
---

# Collect benchmark books

Build the dataset from the library: every book whose LibraForge sidecar kept its original tags becomes a benchmark book, and an applied match is its right answer.
