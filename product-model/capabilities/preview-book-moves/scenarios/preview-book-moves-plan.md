---
kind: primary
routes:
  web: Web
  cli: Command line
steps:
- kind: actor
  actor: library-owner
  text: The owner chooses source, destination and naming options with Apply off.
  entities: []
  contexts:
    web:
      place: web::folder-forge
    cli:
      place: cli
- kind: product
  text: The Product reads audiobook and ebook metadata, creates planned move entries and displays skipped items
    without moving media.
  entities:
  - entity: audiobook
    effect: reads
    facts:
    - Path
    - Title
    - Author
    - Series
    - Identifiers
    - Metadata status
    - Companions
  - entity: ebook
    effect: reads
    facts:
    - Path
    - Title
    - Author
    - Series
    - Publication
    - Genres
    - Summary
    - Cover
    - Metadata status
  - entity: planned-move
    effect: creates
    facts:
    - Source
    - Destination
    - Metadata
    - Review reasons
    - Companions
    - Result
    to: Planned
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
      place: web::folder-forge
    cli:
      place: cli
  actor: library-owner
references:
- kind: code
  role: implementation
  target: scripts/organize-audiobooks-by-metadata-v3_13.py#main
- kind: code
  role: implementation
  target: scripts/organize-audiobooks-by-metadata-v3_13.py#infer_metadata
- kind: code
  role: implementation
  target: app/main.py#build_organizer_command
---

# Preview destinations

## Trigger

The owner wants to organize an import folder.

## Outcome

The Product reads audiobook and ebook metadata, creates planned move entries and displays skipped items without moving media.

## Edge cases

- Case-insensitive skip patterns exclude matching source paths or inferred metadata from moves.
- Unknown authors, ambiguous existing structures and occupied destinations are reported as skipped under the default policy.
- Template filenames apply only to single-file books; multipart groups keep their chapter filenames.
