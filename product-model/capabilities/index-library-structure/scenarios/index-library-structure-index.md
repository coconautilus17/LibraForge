---
kind: primary
routes:
  web: Web
  cli: Command line
steps:
- kind: actor
  actor: library-owner
  text: The owner chooses Index library and exit.
  entities: []
  contexts:
    web:
      place: web::folder-forge
    cli:
      place: cli
- kind: product
  text: The Product reads audiobook locations and grouping metadata and reports the indexed structure count
    without relocation.
  entities:
  - entity: audiobook
    effect: reads
    facts:
    - Path
    - Author
    - Series
  contexts:
    web:
      place: web::folder-forge
    cli:
      place: cli
  actor: library-owner
references:
- kind: code
  role: implementation
  target: scripts/organize-audiobooks-by-metadata-v3_13.py#build_structure_cache
- kind: code
  role: implementation
  target: scripts/organize-audiobooks-by-metadata-v3_13.py#main
---

# Index destination organization

## Trigger

Existing library structure should guide later moves.

## Outcome

The Product reads audiobook locations and grouping metadata and reports the indexed structure count without relocation.
