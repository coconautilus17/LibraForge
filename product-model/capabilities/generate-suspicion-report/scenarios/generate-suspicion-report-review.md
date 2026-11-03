---
kind: primary
routes:
  web: Web
  cli: Command line
steps:
- kind: actor
  actor: library-owner
  text: The owner generates the Suspicion Report for the latest match report.
  entities: []
  contexts:
    web:
      place: web::metadata-forge
    cli:
      place: cli
- kind: product
  text: The Product adds rule-based review reasons to the metadata match evidence and exposes series groups
    for correction.
  entities:
  - entity: metadata-match
    effect: changes
    facts:
    - Review reasons
  - entity: series
    effect: reads
    facts:
    - Name
    - Authors
    - Books
    - Shared metadata
  contexts:
    web:
      place: web::metadata-forge
    cli:
      place: cli
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#generate_suspect_review
- kind: code
  role: implementation
  target: scripts/review-libraforge-report.py
---

# Flag likely-wrong matches

## Trigger

A report is available for a second look.

## Outcome

The Product adds rule-based review reasons to the metadata match evidence and exposes series groups for correction.

## Edge cases

- Missing source reports or a failing review process return an error.
- This review does not use a language model or itself change book metadata.
