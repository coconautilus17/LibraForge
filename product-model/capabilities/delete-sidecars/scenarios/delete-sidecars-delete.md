---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner confirms Delete for the chosen folder and file types.
  entities: []
  contexts:
    web:
      place: web::cleanup
- kind: product
  text: The Product removes the selected audiobook Companions and reports successful deletion counts and file
    errors.
  entities:
  - entity: audiobook
    effect: changes
    facts:
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
  target: app/static/ui-preferences.js
---

# Remove selected companion files

## Trigger

The cleanup preview has been reviewed.

## Outcome

The Product removes the selected audiobook Companions and reports successful deletion counts and file errors.

## Edge cases

- A failure to delete one file is recorded while remaining files are attempted.
