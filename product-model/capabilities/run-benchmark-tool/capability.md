---
availability:
- place: cli
references:
- kind: code
  role: implementation
  target: dev/benchmark/run.sh
- kind: code
  role: implementation
  target: dev/benchmark/lf_bench.py
- kind: code
  role: implementation
  target: dev/benchmark/audiosilo.py
- kind: code
  role: implementation
  target: dev/benchmark/abs_quickmatch.py
- kind: code
  role: implementation
  target: dev/benchmark/grimmory.py
- kind: code
  role: implementation
  target: dev/benchmark/readmeabook.py
- kind: code
  role: implementation
  target: dev/benchmark/bookorbit.py#fetch
- kind: code
  role: implementation
  target: dev/benchmark/bookorbit.py#rows
- kind: code
  role: implementation
  target: dev/benchmark/beets_run.sh
- kind: code
  role: implementation
  target: dev/benchmark/beets_rows.py
domain: benchmark
---

# Run a benchmark tool

Run one matching tool over every benchmark book, in a throwaway instance and the way its own documentation suggests, and record its result per book and its total run time.
