---
kind: primary
routes:
  page: Benchmark page
steps:
- kind: actor
  actor: page-visitor
  text: The visitor filters or searches the book list.
  entities: []
  contexts:
    page:
      place: benchmark-page::books
- kind: product
  text: The Product lists the matching books with LibraForge's outcome and pick, the filters kept in the address.
  entities:
  - entity: benchmark-book
    effect: reads
    facts:
    - Folder
    - Right answer
  - entity: audit-verdict
    effect: reads
    facts:
    - Final verdict
  - entity: benchmark-run
    effect: reads
    facts:
    - Results
  contexts:
    page:
      place: benchmark-page::books
  actor: page-visitor
- kind: actor
  actor: page-visitor
  text: The visitor opens a book.
  entities: []
  contexts:
    page:
      place: benchmark-page::book
- kind: product
  text: The Product shows the book's tags, the right answer beside what LibraForge wrote, and every tool's verdict
    and pick.
  entities:
  - entity: benchmark-book
    effect: reads
    facts:
    - Folder
    - File
    - Original tags
    - Runtime
    - Right answer
  - entity: audit-verdict
    effect: reads
    facts:
    - Final verdict
    - Note
    - Field problems
  - entity: benchmark-run
    effect: reads
    facts:
    - Results
  contexts:
    page:
      place: benchmark-page::book
  actor: page-visitor
references:
- kind: code
  role: implementation
  target: dev/benchmark/report.py
---

# Find and open a book

## Trigger

A visitor wants to see specific results.

## Outcome

The visitor sees the matching books and one book's full detail.
