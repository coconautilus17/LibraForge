---
kind: primary
routes:
  cli: Command line
steps:
- kind: actor
  actor: library-owner
  text: The owner applies the legacy metadata migration with a backup folder.
  entities: []
  contexts:
    cli:
      place: cli
- kind: product
  text: The Product backs up audiobook companion metadata, uses the newer record’s nonblank values and removes
    successfully reconciled legacy files, recording each result.
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
  target: app/abs_client.py#apply_legacy_metadata_json_migration
- kind: code
  role: implementation
  target: app/abs_client.py#reconcile_legacy_metadata_json
---

# Consolidate legacy metadata

## Trigger

The owner elects to apply the migration.

## Outcome

The Product backs up audiobook companion metadata, uses the newer record’s nonblank values and removes successfully reconciled legacy files, recording each result.

## Edge cases

- A failed backup prevents reconciliation of that book.
- Unreadable files and failed upstream changes remain for later review.
- The report is written when application is interrupted.
