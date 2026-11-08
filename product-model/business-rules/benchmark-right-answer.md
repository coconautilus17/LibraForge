---
appliesTo:
- type: entity
  id: benchmark-book
  facts:
  - Right answer
  - Answer source
references:
- kind: code
  role: implementation
  target: dev/benchmark/answers.py#fetch
- kind: code
  role: implementation
  target: dev/benchmark/collect.py#collect
- kind: code
  role: implementation
  target: dev/benchmark/review_lib.py#confirm
---

# A book's right answer is its confirmed listing's own record

A book's right answer is the listing confirmed as that book, as the catalog itself records it, read by its ASIN:
its title, every author, every narrator, every series it is listed in with its number there, and its runtime. A
listing confirmed in the library, in the review library or by hand from a candidate is a confirmed listing; a file
name is not. A book in several series is answered by any of them. A book with no confirmed listing has no right
answer: it is reported, not scored, and shows no answer.

## Rationale

The catalog's record is complete and the same for every tool, while what was once written to a book can carry that
run's mistakes. A lookup by ASIN is not limited to the market the runs were made from.
