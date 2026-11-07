---
kind: primary
routes:
  page: Benchmark page
steps:
- kind: actor
  actor: page-visitor
  text: The visitor chooses to report the book's result.
  entities: []
  contexts:
    page:
      place: benchmark-page::book
- kind: product
  text: The Product opens a GitHub issue form naming the book.
  entities:
  - entity: benchmark-book
    effect: reads
    facts:
    - Folder
  contexts:
    page:
      place: benchmark-page::book
  actor: page-visitor
references:
- kind: code
  role: implementation
  target: dev/benchmark/report.py
---

# Report a wrong result

## Trigger

A visitor thinks a book's verdict or right answer is wrong.

## Outcome

A new GitHub issue opens with the book's folder filled in.
