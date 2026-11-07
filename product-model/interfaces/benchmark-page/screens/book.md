---
entities:
- entity: benchmark-book
  shows:
  - Folder
  - File
  - Original tags
  - Runtime
  - Right answer
- entity: audit-verdict
  shows:
  - Final verdict
  - Note
  - Field problems
- entity: benchmark-run
  shows:
  - Results
references:
- kind: code
  role: implementation
  target: dev/benchmark/report.py
---

# Book

One book: its original tags, the right answer and what LibraForge wrote side by side, every tool's verdict and
pick, and how LibraForge got there (what it read, its searches, candidates and trace).
