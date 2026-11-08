---
kind: primary
routes:
  cli: Command line
steps:
- kind: actor
  actor: library-owner
  text: The owner compares a tool's new results with its audited ones.
  entities: []
  contexts: &id001
    cli:
      place: cli
- kind: product
  text: The Product keeps the verdict of every unchanged result, settles a changed one by rule only when the evidence
    is plain, and lists the rest for hand review.
  entities:
  - entity: benchmark-run
    effect: reads
    facts:
    - Results
  - entity: audit-verdict
    effect: changes
    facts:
    - Hand verdict
  contexts: *id001
  actor: library-owner
references:
- kind: code
  role: implementation
  target: dev/benchmark/audit_check.py
---

# Judge a tool's new run

## Trigger

A tool was run again over the same dataset, as a new build or version.

## Outcome

Verdict files for the new run exist, with every changed book either settled by rule or listed for review.

## Edge cases

- An unchanged result is the same status, chosen listing and written fields.
- A changed result is settled by rule only when it is the confirmed answer's listing, a listing another tool was judged right or another recording on, or a series-only write into the book's own series.
- A held or skipped book is never judged a held right pick by rule; only by hand.
