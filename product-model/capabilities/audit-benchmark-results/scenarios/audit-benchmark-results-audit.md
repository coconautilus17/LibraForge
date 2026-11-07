---
kind: primary
routes:
  cli: Command line
steps:
- kind: actor
  actor: library-owner
  text: The owner writes a hand verdict per book and tool into the verdict files and starts the field checks.
  entities: []
  contexts: &id001
    cli:
      place: cli
- kind: product
  text: The Product rebuilds what each tool left on each book from its results and the original tags, checks every
    field against the right answer, and saves the final verdicts.
  entities:
  - entity: benchmark
    effect: reads
    facts:
    - Dataset
    - Runs
    - Audit
  - entity: benchmark-run
    effect: reads
    facts:
    - Results
  - entity: audit-verdict
    effect: creates
    facts:
    - Hand verdict
    - Note
    - Field problems
    - Final verdict
  contexts: *id001
  actor: library-owner
references:
- kind: code
  role: implementation
  target: dev/benchmark/audit.py
- kind: code
  role: implementation
  target: dev/benchmark/audit_check.py
---

# Audit every result

## Trigger

Every tool in the manifest has a run.

## Outcome

Every book has a final verdict per tool, and every book where the field checks and the hand verdict disagree is listed for a second look.

## Edge cases

- A missing verdict line or an unknown code stops the audit.
