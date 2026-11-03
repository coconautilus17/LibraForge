---
kind: primary
routes:
  cli: Command line
steps:
- kind: actor
  actor: library-owner
  text: The owner applies the author-name migration.
  entities: []
  contexts:
    cli:
      place: cli
- kind: product
  text: The Product changes audiobook author metadata and paths, writes the change log and skips folder collisions
    it cannot merge.
  entities:
  - entity: audiobook
    effect: changes
    facts:
    - Author
    - Path
    - Companions
  contexts:
    cli:
      place: cli
  actor: library-owner
references:
- kind: code
  role: implementation
  target: scripts/normalize-author-names.py#main
- kind: code
  role: implementation
  target: scripts/normalize-author-names.py#apply_folder_change
---

# Normalize local author names

## Trigger

The owner has chosen to migrate existing names.

## Outcome

The Product changes audiobook author metadata and paths, writes the change log and skips folder collisions it cannot merge.

## Edge cases

- Sidecar and optional tag fields are changed before folders move.
