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
  target: dev/benchmark/collect.py#collect
- kind: code
  role: implementation
  target: dev/benchmark/collect.py#parse_dump_name
- kind: code
  role: implementation
  target: dev/benchmark/review_lib.py#confirm
---

# A book's right answer is its applied listing, or else its file name

A library book's right answer is the match applied to it in the library: that listing's ASIN and the title, author,
narrator, series and number LibraForge wrote when it applied it. An imported book's right answer is the series,
number and title its `Author; Series; Book NN; Title` file name states, with no narrator, until the review library
confirms a listing. A book with neither has no right answer and is reported, not scored.

## Rationale

The applied matches were reviewed in the library, so they are the best record of which listing a book is. The
fields beside the ASIN are what was written at the time, so they can carry that older run's mistakes.
