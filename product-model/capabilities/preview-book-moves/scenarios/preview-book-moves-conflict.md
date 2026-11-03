---
kind: edge
routes:
  web: Web
  cli: Command line
steps:
- kind: actor
  actor: library-owner
  text: The owner previews the selected folder.
  entities: []
  contexts:
    web:
      place: web::folder-forge
    cli:
      place: cli
- kind: product
  text: The Product creates a skipped planned move with the destination and review reason, leaving the book
    in place.
  entities:
  - entity: planned-move
    effect: creates
    facts:
    - Source
    - Destination
    - Metadata
    - Review reasons
    - Companions
    - Result
    to: Skipped
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

# Show skipped destinations

## Trigger

A target is already occupied or the series structure is ambiguous.

## Outcome

The Product creates a skipped planned move with the destination and review reason, leaving the book in place.
