---
domain: benchmark
references:
- kind: code
  role: implementation
  target: dev/benchmark/collect.py#collect
- kind: code
  role: implementation
  target: dev/benchmark/collect.py#import_dump
---

# Benchmark book

One audiobook in its original state, before any tool matched it: the case every tool is given.

## Information kept

- **Folder** — The book's folder path, which every tool sees as the book's place in a library.
- **File** — Its audio file's name.
- **Original tags** — The tags the file arrived with, saved before LibraForge first wrote anything.
- **Runtime** — The book's real length.
- **Right answer** — The confirmed listing's own record: its ASIN, title, every author, every narrator, every series with its number, and runtime.
- **Answer source** — Where the listing was confirmed (the library, the review library, or by hand from a candidate), or none.
- **Origin** — This library, or another library's tag dump.
