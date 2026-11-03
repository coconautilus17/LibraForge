---
kind: primary
routes:
  web: Web
  cli: Command line
steps:
- kind: actor
  actor: library-owner
  text: The owner turns Apply on and picks a write mode.
  entities: []
  contexts:
    web:
      place: web::metadata-forge
    cli:
      place: cli
- kind: product
  text: The Product changes the audiobook’s eligible metadata, saves the applicable original tags, records
    the metadata match’s write outcome and completes the run.
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
  target: scripts/audible-metadata-fixer-v5.py#main
- kind: code
  role: implementation
  target: scripts/audible-metadata-fixer-v5.py#decide_write
- kind: code
  role: implementation
  target: app/abs_client.py#sync_book_metadata
---

# Apply matched metadata

## Trigger

The owner chooses an applying batch run.

## Outcome

The Product changes the audiobook’s eligible metadata, saves the applicable original tags, records the metadata match’s write outcome and completes the run.

## Edge cases

- Grouped chapter files receive merge metadata; independently meaningful books are not collapsed merely because they share a folder.
- Known Audiobookshelf items use direct metadata synchronization; books not yet known use bootstrap metadata files.
- Metadata-only mode leaves embedded audio tags untouched.
- An individual failure is reported with its target.
