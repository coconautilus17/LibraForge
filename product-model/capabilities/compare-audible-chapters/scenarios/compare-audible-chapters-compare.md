---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner chooses Compare to Audible.
  entities: []
  contexts:
    web:
      place: web::chapter-forge
- kind: product
  text: The Product reads chapter entries and presents the official comparison without changing the saved list.
  entities:
  - entity: chapter
    effect: reads
    facts:
    - Title
    - Timing
    - Evidence
    - Manual
  - entity: audiobook
    effect: reads
    facts:
    - Identifiers
  contexts:
    web:
      place: web::chapter-forge
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#audible_compare_chapters
- kind: code
  role: implementation
  target: app/static/chapter-forge.js#compareToAudible
---

# Compare against official timing

## Trigger

The loaded source has or is given an ASIN.

## Outcome

The Product reads chapter entries and presents the official comparison without changing the saved list.

## Edge cases

- Missing ASIN or unverified source chapter data produces a lookup error.
