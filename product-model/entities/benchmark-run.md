---
domain: benchmark
references:
- kind: code
  role: implementation
  target: dev/benchmark/run.sh
- kind: code
  role: implementation
  target: dev/benchmark/lf_bench.py
---

# Benchmark run

One tool's pass over every benchmark book.

## Information kept

- **Tool** — The matching tool and its version or LibraForge build.
- **Settings** — Provider, workers and options it ran with.
- **Results** — Per book: whether it wrote, held or left the book, the listing it chose and the details it gives the book.
- **Run time** — The run's total wall time.
- **Run date** — The day the run was made.
