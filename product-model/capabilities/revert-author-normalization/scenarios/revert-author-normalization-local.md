---
kind: primary
routes:
  cli: Command line
steps:
- kind: actor
  actor: library-owner
  text: The owner reverts using a saved change log.
  entities: []
  contexts:
    cli:
      place: cli
- kind: product
  text: The Product restores audiobook local paths and metadata from the logged original values.
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
  target: scripts/normalize-author-names.py#revert
---

# Undo logged local normalization

## Trigger

A local normalization log is available.

## Outcome

The Product restores audiobook local paths and metadata from the logged original values.
