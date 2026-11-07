---
kind: primary
routes:
  cli: Command line
steps:
- kind: actor
  actor: library-owner
  text: The owner publishes from the manifest.
  entities: []
  contexts: &id001
    cli:
      place: cli
- kind: product
  text: The Product builds the page, the downloadable book list and the public mock, and commits them for the owner
    to push.
  entities:
  - entity: benchmark
    effect: reads
    facts:
    - Dataset
    - Runs
    - Audit
    - LibraForge build
    - Sales rights
    - Hidden books
  - entity: benchmark-book
    effect: reads
    facts:
    - Folder
    - File
    - Original tags
    - Runtime
    - Right answer
    - Answer source
  - entity: benchmark-run
    effect: reads
    facts:
    - Tool
    - Settings
    - Results
    - Run time
  - entity: audit-verdict
    effect: reads
    facts:
    - Final verdict
    - Note
    - Field problems
  - entity: audit-sample
    effect: reads
    facts:
    - Findings
  contexts: *id001
  actor: library-owner
references:
- kind: code
  role: implementation
  target: dev/benchmark/publish_pages.sh
- kind: code
  role: implementation
  target: dev/benchmark/report.py
---

# Publish the page

## Trigger

The audit is final.

## Outcome

The page, the book list and the mock files are committed to the published branch, ready to push after a look.

## Edge cases

- Built without publishing (report.py without --public), the page lists every tag and stays in the dataset folder.
