---
kind: alternate
routes:
  page: Benchmark page
steps:
- kind: actor
  actor: page-visitor
  text: The visitor downloads the mock files.
  entities: []
  contexts:
    page:
      place: benchmark-page::books
- kind: product
  text: 'The Product serves the public mock: one second of silence per book with only the tags a matcher reads.'
  entities:
  - entity: benchmark-book
    effect: reads
    facts:
    - Folder
    - File
    - Original tags
  contexts:
    page:
      place: benchmark-page::books
  actor: page-visitor
references:
- kind: code
  role: implementation
  target: dev/benchmark/publish_pages.sh
- kind: code
  role: implementation
  target: dev/benchmark/bo_mock.py
---

# Download the mock files

## Trigger

A visitor wants to run a tool on the same books.

## Outcome

The visitor has every book as a silent file carrying its matcher tags at its folder path.
