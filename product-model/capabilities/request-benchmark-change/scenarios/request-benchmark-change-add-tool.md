---
kind: alternate
routes:
  page: Benchmark page
steps:
- kind: actor
  actor: page-visitor
  text: The visitor asks for a tool to be added.
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

# Suggest a tool

## Trigger

A visitor wants a tool to be added.

## Outcome

A new GitHub issue opens with the questions the request needs.
