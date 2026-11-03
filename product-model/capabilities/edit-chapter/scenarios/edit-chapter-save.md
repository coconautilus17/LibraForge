---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner changes a label or start time and saves.
  entities: []
  contexts:
    web:
      place: web::chapter-forge
- kind: product
  text: The Product changes chapter titles and timing, sorts entries by start, assigns default labels where
    blank and marks saved entries as manual.
  entities:
  - entity: chapter
    effect: changes
    facts:
    - Title
    - Timing
    - Manual
  contexts:
    web:
      place: web::chapter-forge
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#save_chaptering
- kind: code
  role: implementation
  target: app/static/chapter-forge.js#setChapterStartFromEvidence
---

# Save corrected timing

## Trigger

A chapter needs a manual correction.

## Outcome

The Product changes chapter titles and timing, sorts entries by start, assigns default labels where blank and marks saved entries as manual.

## Edge cases

- Start times are constrained to zero or later and end times to at least the start.
