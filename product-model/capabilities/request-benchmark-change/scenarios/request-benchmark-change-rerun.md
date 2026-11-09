---
kind: primary
routes:
  page: Benchmark page
steps:
- kind: actor
  actor: page-visitor
  text: The visitor asks for a tool to be tried again.
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

# Ask for a re-run

## Trigger

A visitor wants a tool to be tried again.

## Outcome

A new GitHub issue opens with the questions the request needs.
