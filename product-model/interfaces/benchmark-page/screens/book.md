---
entities:
- entity: benchmark-book
  shows:
  - Folder
  - File
  - Original tags
  - Runtime
  - Right answer
  - Answer source
- entity: audit-verdict
  shows:
  - Final verdict
  - Note
  - Field problems
- entity: benchmark-run
  shows:
  - Tool
  - Results
references:
- kind: code
  role: implementation
  target: dev/benchmark/report.py
---

# Book

One book: its original tags, the right answer, and every tool's result after its write (each scored field and the
ASIN, every value marked right or wrong) side by side; every tool's verdict with its reason; and how LibraForge got
there (what it read, its searches, candidates and trace). A book with no right answer says so and shows no answer.
