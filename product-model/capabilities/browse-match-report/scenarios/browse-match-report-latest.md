---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner opens the Match Report and chooses a filter.
  entities: []
  contexts:
    web:
      place: web::metadata-forge
- kind: product
  text: The Product presents metadata match details and detected series groups, with a selected local target
    loadable into Manual Review.
  entities:
  - entity: metadata-match
    effect: reads
    facts:
    - Book
    - Candidate
    - Provider
    - Score
    - Edit mode
    - Review reasons
    - Write outcome
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
  actor: library-owner
- kind: product
  actor: library-owner
  text: The Product carries a selected audiobook into Manual Review.
  entities:
  - entity: audiobook
    effect: reads
    facts:
    - Path
  contexts:
    web:
      place: web::manual-review
references:
- kind: code
  role: implementation
  target: app/main.py#get_latest_report
- kind: code
  role: implementation
  target: app/main.py#report_for_api
- kind: code
  role: implementation
  target: app/static/app.js
---

# Review the latest metadata results

## Trigger

A metadata run has completed.

## Outcome

The Product presents metadata match details and detected series groups, with a selected local target loadable into Manual Review.

## Edge cases

- No previous metadata report produces an empty or missing-report result rather than a different tool’s report.
