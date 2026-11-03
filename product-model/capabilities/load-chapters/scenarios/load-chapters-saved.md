---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner loads the selected book’s chapters.
  entities:
  - entity: chapter
    effect: reads
    facts:
    - Title
    - Timing
    - Evidence
    - Manual
  contexts:
    web:
      place: web::chapter-forge
- kind: product
  text: The Product presents the audiobook source and available chapter timing, labels and evidence for review.
  entities:
  - entity: audiobook
    effect: reads
    facts:
    - Path
    - Audio
    - Identifiers
  - entity: chapter
    effect: reads
    facts:
    - Title
    - Timing
    - Evidence
    - Manual
  contexts:
    web:
      place: web::chapter-forge
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#load_chaptering
- kind: code
  role: implementation
  target: app/chaptering.py#load_existing_result
---

# Read a book’s chapter evidence

## Trigger

A source is selected.

## Outcome

The Product presents the audiobook source and available chapter timing, labels and evidence for review.

## Edge cases

- A source without a saved result starts with no saved chapter entries.
