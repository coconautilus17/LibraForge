---
kind: alternate
routes:
  page: Benchmark page
steps:
- kind: actor
  actor: page-visitor
  text: The visitor asks for their books to be added.
  entities: []
  contexts:
    page:
      place: benchmark-page::results
- kind: product
  text: The Product opens the matching GitHub issue form.
  entities: []
  contexts:
    page:
      place: benchmark-page::results
  actor: page-visitor
references:
- kind: code
  role: implementation
  target: dev/benchmark/report.py
---

# Add your books

## Trigger

A visitor wants their books to be added.

## Outcome

A new GitHub issue opens with the questions the request needs.

## Edge cases

- The book dump the issue asks for holds each file's path, length and tags, never the audio.
