---
kind: primary
routes:
  cli: Command line
steps:
- kind: actor
  actor: library-owner
  text: The owner reads the sales rights and counts for the market the tools were tried from.
  entities: []
  contexts: &id001
    cli:
      place: cli
- kind: product
  text: The Product saves each answer's sales rights and the counts, never the market itself.
  entities:
  - entity: benchmark
    effect: changes
    facts:
    - Sales rights
    - Hidden books
  - entity: audit-verdict
    effect: reads
    facts:
    - Final verdict
  contexts: *id001
  actor: library-owner
references:
- kind: code
  role: implementation
  target: dev/benchmark/geo.py
---

# Count the books search hid

## Trigger

The audit is final.

## Outcome

The page can say how many confirmed answers search hid and how many each tool still got right.
