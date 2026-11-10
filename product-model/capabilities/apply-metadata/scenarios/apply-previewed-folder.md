---
kind: alternate
routes:
  web: Web
  cli: Command line
steps:
- kind: actor
  actor: library-owner
  text: The owner applies a folder that a preview covered.
  entities: []
  contexts:
    web:
      place: web::metadata-forge
    cli:
      place: cli
- kind: product
  text: The Product takes each unchanged book's metadata match from the preview and searches only the
    other books.
  entities:
  - entity: audiobook
    effect: reads
    facts:
    - Path
    - Audio
  - entity: metadata-match
    effect: reads
    facts:
    - Book
    - Candidate
    - Provider
    - Score
    - Edit mode
    - Review reasons
  contexts:
    web:
      place: web::metadata-forge
    cli:
      place: cli
  actor: library-owner
- kind: product
  text: The Product changes the audiobook's eligible metadata, records the metadata match's write outcome
    and completes the run.
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
    cli:
      place: cli
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/fixer/plan.py
- kind: code
  role: implementation
  target: scripts/audible-metadata-fixer-v5.py#main
---

# Apply a previewed folder

## Trigger

The owner applies a folder after previewing it.

## Outcome

Unchanged books receive the matches the preview showed without being searched again; the run completes with their write outcomes.

## Edge cases

- A book whose audio files changed since the preview is searched.
- A book the preview did not cover is searched.
- A preview made with other matching settings is not used, and every book is searched.
- A book applied by hand after the preview is left alone.
