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

Give every book a confirmed listing where one exists, and read each confirmed listing's own record as the book's right answer: confirm books in a throwaway review library or by hand from a candidate, then read every confirmed listing from the catalog by its ASIN.
