---
kind: primary
routes:
  page: Benchmark page
steps:
- kind: actor
  actor: page-visitor
  text: The visitor opens the comparison page.
  entities: []
  contexts:
    page:
      place: benchmark-page::results
- kind: product
  text: The Product shows each tool's share of fully correct, partly right, wrong, held and unwritten books, best
    first.
  entities:
  - entity: benchmark
    effect: reads
    facts:
    - Runs
    - LibraForge build
    - Hidden books
  - entity: audit-verdict
    effect: reads
    facts:
    - Final verdict
    - Field problems
  - entity: audit-sample
    effect: reads
    facts:
    - Findings
  contexts:
    page:
      place: benchmark-page::results
  actor: page-visitor
references:
- kind: code
  role: implementation
  target: dev/benchmark/report.py
---

# Read the results

## Trigger

A visitor opens the page.

## Outcome

The visitor sees every tool's outcomes, run time and notes, and the audit's error rates.
