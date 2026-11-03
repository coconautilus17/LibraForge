---
kind: primary
routes:
  web: Web
  cli: Command line
steps:
- kind: actor
  actor: library-owner
  text: The owner chooses the folder, provider and matching options with Apply off.
  entities: []
  contexts:
    web:
      place: web::metadata-forge
    cli:
      place: cli
- kind: product
  text: The Product reads the audiobook clues, finds a metadata match and presents proposed values and write
    destinations without applying those values.
  entities:
  - entity: audiobook
    effect: reads
    facts:
    - Path
    - Title
    - Author
    - Narrator
    - Series
    - Publication
    - Identifiers
    - Genres
    - Audio
    - Metadata status
    - Companions
  - entity: metadata-match
    effect: creates
    facts:
    - Book
    - Candidate
    - Provider
    - Score
    - Edit mode
    - Review reasons
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
  target: scripts/audible-metadata-fixer-v5.py#search_item
- kind: code
  role: implementation
  target: scripts/audible-metadata-fixer-v5.py#main
- kind: code
  role: implementation
  target: app/main.py#build_command
---

# Preview a confident match

## Trigger

The owner starts a default metadata run.

## Outcome

The Product reads the audiobook clues, finds a metadata match and presents proposed values and write destinations without applying those values.

## Edge cases

- Already clean processed books are skipped; incomplete saved matches can supply recovery values without a fresh lookup.
- Full metadata and series-only matches retain their distinct edit scope.
- A previously manually applied book keeps the human-selected match during ordinary batch reprocessing.
- A book whose last match was series only, or another recording with no real ASIN of its own, is searched again instead of skipped.
- A book Audible's search leaves out is matched through the other books of its series on Audible, or through AudioSilo, and written from its own Audible listing.
- An AudioSilo match whose ASIN Audible doesn't list is written from AudioSilo's record, and the book keeps its own ASIN.
