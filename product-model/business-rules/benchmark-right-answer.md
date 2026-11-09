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

# A book's right answer is its confirmed edition's own record

A book's right answer is the edition confirmed as that book, as its own catalog records it: Audible's listing read
by its ASIN when the edition is on Audible, otherwise the record of the catalog that publishes it (a publisher's
own store by ISBN, the community database by its work), or the fields the owner confirms by hand when no catalog
has it. The record holds its title, every author, every narrator, every series it is in with its number there, and
its runtime, with every ID the edition has (ASIN, ISBN, community work, Goodreads). An edition confirmed in the
library, in the review library or by hand from a candidate is a confirmed edition; a file name is not. A book in
several series is answered by any of them. A book with no confirmed edition has no right answer: it is reported,
not scored, and shows no answer.

## Rationale

Not every edition is on Audible, and an ASIN applied to a book can belong to another recording of it. The
edition's own record is complete and the same for every tool, while what was once written to a book can carry that
run's mistakes. A lookup by ASIN is not limited to the market the runs were made from.
