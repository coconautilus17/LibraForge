---
kind: alternate
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner applies with Search and match again chosen.
  entities: []
  contexts:
    web:
      place: web::metadata-forge
- kind: product
  text: The Product searches every book, including books a preview covered, then changes the audiobook's
    eligible metadata, records the metadata match's write outcome and completes the run.
  entities:
  - entity: audiobook
    effect: changes
    facts:
    - Title
    - Author
    - Narrator
    - Series
    - Publication
    - Identifiers
    - Genres
    - Summary
    - Cover
    - Metadata status
    - Original metadata
    - Companions
  - entity: metadata-match
    effect: changes
    facts:
    - Write outcome
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
      place: web::metadata-forge
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#RunRequest
- kind: code
  role: implementation
  target: scripts/audible-metadata-fixer-v5.py#main
---

# Search every book again

## Trigger

The owner wants fresh matches instead of the preview's.

## Outcome

Every book is matched by a new search, so results can differ from the preview's when providers answer differently; the run completes with their write outcomes.
