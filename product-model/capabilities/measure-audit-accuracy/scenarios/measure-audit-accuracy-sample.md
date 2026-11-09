---
kind: primary
routes:
  cli: Command line
steps:
- kind: actor
  actor: library-owner
  text: The owner draws a sample with a fixed seed and judges its sheets again.
  entities: []
  contexts: &id001
    cli:
      place: cli
- kind: product
  text: The Product draws the books, prints a sheet per 25 of them with every tool's result and verdict, and counts
    the findings into the page's error rates.
  entities:
  - entity: audit-verdict
    effect: reads
    facts:
    - Final verdict
    - Field problems
    - Note
  - entity: audit-sample
    effect: creates
    facts:
    - Books
    - Seed
    - Findings
  contexts: *id001
  actor: library-owner
references:
- kind: code
  role: implementation
  target: dev/benchmark/reaudit_sample.py
- kind: code
  role: implementation
  target: dev/benchmark/audit_check.py
---

# Audit a sample again

## Trigger

The audit is complete.

## Outcome

The rate of wrong verdicts is known, every kind of error found is corrected for every book, and the page reports it.

## Edge cases

- A validation sample never redraws a book the first sample took.
