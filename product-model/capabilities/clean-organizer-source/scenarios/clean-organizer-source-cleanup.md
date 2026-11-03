---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner chooses to clean up the source folder.
  entities: []
  contexts:
    web:
      place: web::folder-forge
- kind: product
  text: The Product removes eligible audiobook companion caches and empty folders and reports removals and
    errors.
  entities:
  - entity: audiobook
    effect: changes
    facts:
    - Companions
  contexts:
    web:
      place: web::folder-forge
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#organizer_cleanup_source
---

# Clean an import folder

## Trigger

Books have been moved out of the source folder.

## Outcome

The Product removes eligible audiobook companion caches and empty folders and reports removals and errors.

## Edge cases

- Non-empty directories and the source root remain.
