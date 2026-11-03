---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner chooses a folder and which files to remove, then previews.
  entities: []
  contexts:
    web:
      place: web::cleanup
- kind: product
  text: The Product reads audiobook Companions and reports matching counts, bytes and sample paths without
    deleting them.
  entities:
  - entity: audiobook
    effect: reads
    facts:
    - Path
    - Companions
  contexts:
    web:
      place: web::cleanup
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#cleanup_sidecars
- kind: code
  role: implementation
  target: app/main.py#collect_cleanup_targets
---

# Inspect cleanup candidates

## Trigger

The owner wants to remove leftover metadata files.

## Outcome

The Product reads audiobook Companions and reports matching counts, bytes and sample paths without deleting them.

## Edge cases

- Metadata-file mode includes matching metadata files regardless of which tool originally wrote them.
