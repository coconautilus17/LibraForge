---
kind: alternate
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner chooses Load into Manual Review for the ebook.
  entities:
  - entity: ebook
    effect: reads
    facts:
    - Path
  contexts:
    web:
      place: web::metadata-forge
- kind: product
  text: The Product carries the ebook path into its Manual Review form.
  entities:
  - entity: ebook
    effect: reads
    facts:
    - Path
  contexts:
    web:
      place: web::metadata-forge
  actor: library-owner
- kind: product
  actor: library-owner
  text: The Product loads the selected ebook target for review.
  entities:
  - entity: ebook
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

# Open a reported ebook for review

## Trigger

A report contains an ebook target.

## Outcome

The Product carries the ebook path into its Manual Review form.
