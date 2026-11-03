---
kind: primary
routes:
  web: Web
  cli: Command line
steps:
- kind: actor
  actor: library-owner
  text: The owner restores original tags for the selected folder.
  entities: []
  contexts:
    web:
      place: web::metadata-forge
    cli:
      place: cli
- kind: product
  text: The Product restores audiobook embedded fields from Original metadata and reports successful and skipped
    files.
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
    - Explicit
    - Summary
    - Metadata status
  contexts:
    web:
      place: web::metadata-forge
    cli:
      place: cli
  actor: library-owner
references:
- kind: code
  role: implementation
  target: scripts/audible-metadata-fixer-v5.py#restore_metadata_backups
- kind: code
  role: implementation
  target: scripts/audible-metadata-fixer-v5.py#restore_metadata_from_backup
- kind: code
  role: implementation
  target: app/main.py#build_command
---

# Restore saved original tags

## Trigger

The owner wants to undo previous tag changes.

## Outcome

The Product restores audiobook embedded fields from Original metadata and reports successful and skipped files.

## Edge cases

- Restoring embedded metadata is not a promise to undo Audiobookshelf edits or organizer moves.
- A file that fails to restore is counted as failed with its error, and the remaining files are still restored.
