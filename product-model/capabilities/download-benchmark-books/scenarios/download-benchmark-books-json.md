---
kind: primary
routes:
  page: Benchmark page
steps:
- kind: actor
  actor: page-visitor
  text: The visitor downloads the book list.
  entities: []
  contexts:
    page:
      place: benchmark-page::books
- kind: product
  text: The Product serves every book with its matcher tags, right answer and every tool's verdict, pick and result.
  entities:
  - entity: benchmark-book
    effect: reads
    facts:
    - Folder
    - File
    - Original tags
    - Runtime
    - Right answer
    - Answer source
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
      place: benchmark-page::books
  actor: page-visitor
references:
- kind: code
  role: implementation
  target: dev/benchmark/report.py
---

# Download the book list

## Trigger

A visitor wants to recount or reuse the results.

## Outcome

The visitor has every book and every verdict as JSON.
