---
kind: edge
routes:
  web: Web
  cli: Command line
steps:
- kind: actor
  actor: library-owner
  text: The owner applies matching to the selected folder.
  entities: []
  contexts:
    web:
      place: web::metadata-forge
    cli:
      place: cli
- kind: product
  text: The Product leaves the conflicting audiobook metadata unchanged and records the metadata match’s duplicate
    review reason and skipped write outcome.
  entities:
  - entity: audiobook
    effect: reads
    facts:
    - Path
    - Identifiers
    - Metadata status
  - entity: metadata-match
    effect: changes
    facts:
    - Review reasons
    - Write outcome
  contexts:
    web:
      place: web::metadata-forge
    cli:
      place: cli
  actor: library-owner
references:
- kind: code
  role: implementation
  target: scripts/audible-metadata-fixer-v5.py#main
- kind: code
  role: implementation
  target: scripts/audible-metadata-fixer-v5.py#decide_write
- kind: code
  role: implementation
  target: app/abs_client.py#sync_book_metadata
---

# Keep duplicate identity conflicts for review

## Trigger

Distinct books resolve to the same conflicting Audible identity.

## Outcome

The Product leaves the conflicting audiobook metadata unchanged and records the metadata match’s duplicate review reason and skipped write outcome.
