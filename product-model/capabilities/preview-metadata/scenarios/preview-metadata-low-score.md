---
kind: validation
routes:
  web: Web
  cli: Command line
steps:
- kind: actor
  actor: library-owner
  text: The owner previews matching for the folder.
  entities: []
  contexts:
    web:
      place: web::metadata-forge
    cli:
      place: cli
- kind: product
  text: The Product records the metadata match’s score and reason for skipping rather than proposing an editable
    match.
  entities:
  - entity: metadata-match
    effect: creates
    facts:
    - Book
    - Candidate
    - Provider
    - Score
    - Edit mode
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
  target: scripts/audible-metadata-fixer-v5.py#search_item
- kind: code
  role: implementation
  target: scripts/audible-metadata-fixer-v5.py#main
- kind: code
  role: implementation
  target: app/main.py#build_command
---

# Show a below-threshold result

## Trigger

The best candidate is below the chosen minimum score or lacks title or author.

## Outcome

The Product records the metadata match’s score and reason for skipping rather than proposing an editable match.
