---
kind: primary
routes:
  cli: Command line
steps:
- kind: actor
  actor: library-owner
  text: The owner previews the author-name migration.
  entities: []
  contexts:
    cli:
      place: cli
- kind: product
  text: The Product reads audiobook author metadata and paths and presents the folder and field changes without
    applying them.
  entities:
  - entity: audiobook
    effect: reads
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
  target: scripts/normalize-author-names.py#plan_folder_changes
---

# Preview existing author names

## Trigger

The owner wants existing local names to follow the initials scheme.

## Outcome

The Product reads audiobook author metadata and paths and presents the folder and field changes without applying them.

## Edge cases

- The scheme must be enabled unless the operator explicitly requests running independently of that preference.
