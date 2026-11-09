---
availability:
- place: cli
references:
- kind: code
  role: implementation
  target: dev/benchmark/answers.py
- kind: code
  role: implementation
  target: dev/benchmark/review_lib.py#build
- kind: code
  role: implementation
  target: dev/benchmark/review_lib.py#confirm
domain: benchmark
---

# Confirm benchmark answers

Give every book a confirmed edition where one exists, and keep that edition's own record as the book's right answer: confirm books in a throwaway review library or by hand from a candidate (corrected, or typed in when no catalog has the edition), then read every confirmed Audible listing from the catalog by its ASIN.
