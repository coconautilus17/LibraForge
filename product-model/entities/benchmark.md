---
singleton: true
domain: benchmark
references:
- kind: code
  role: implementation
  target: dev/benchmark/bench_data.py
- kind: code
  role: implementation
  target: dev/benchmark/manifest.example.json
---

# Benchmark

The one benchmark the page is built from: which files make it up, named once in its manifest.

## Information kept

- **Dataset** — The benchmark books.
- **Runs** — Each tool's run, its results and run time.
- **Audit** — The hand verdicts, the final verdicts and the second-audit samples.
- **LibraForge build** — The LibraForge commit its LibraForge run used.
- **Sales rights** — Where Audible sells each confirmed answer's listing.
- **Hidden books** — How many confirmed answers Audible's search couldn't show where the runs were made, and how many each tool still got right.
