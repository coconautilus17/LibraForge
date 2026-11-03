---
kind: primary
routes:
  cli: Command line
steps:
- kind: actor
  actor: library-owner
  text: The owner previews the legacy metadata migration, its default mode.
  entities: []
  contexts:
    cli:
      place: cli
- kind: product
  text: The Product reads audiobook Companions and library metadata and writes a review report without changing
    media or Audiobookshelf.
  entities:
  - entity: audiobook
    effect: reads
    facts:
    - Path
    - Companions
  contexts:
    cli:
      place: cli
  actor: library-owner
references:
- kind: code
  role: implementation
  target: scripts/migrate-legacy-metadata-json.py#main
- kind: code
  role: implementation
  target: app/abs_client.py#plan_legacy_metadata_json_migration
---

# Plan legacy metadata consolidation

## Trigger

Audiobookshelf is configured and the library paths are available.

## Outcome

The Product reads audiobook Companions and library metadata and writes a review report without changing media or Audiobookshelf.
