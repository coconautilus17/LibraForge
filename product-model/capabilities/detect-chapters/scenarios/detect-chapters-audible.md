---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner picks the official Audible backend and starts detection.
  entities: []
  contexts:
    web:
      place: web::chapter-forge
- kind: product
  text: The Product creates chapter entries from the verified official timings, saves the audiobook chapter
    artifacts and completes the run.
  entities:
  - entity: chapter
    effect: creates
    facts:
    - Title
    - Timing
    - Evidence
    - Manual
  - entity: audiobook
    effect: changes
    facts:
    - Companions
  - entity: run
    effect: creates
    facts:
    - Tool
    - Target
    - Options
    - Progress
    - Results
    - Timing
    to: Completed
  contexts:
    web:
      place: web::chapter-forge
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#run_chaptering_worker
- kind: code
  role: implementation
  target: app/main.py#run_audible_chapters_backend
- kind: code
  role: implementation
  target: app/chaptering.py
---

# Use verified Audible chapters

## Trigger

A source has an ASIN. Without a connected Audible account the lookup uses Audible’s public catalog.

## Outcome

The Product creates chapter entries from the verified official timings, saves the audiobook chapter artifacts and completes the run.

## Edge cases

- No ASIN, no verified chapter data or an empty chapter list fails with an explanatory result.
