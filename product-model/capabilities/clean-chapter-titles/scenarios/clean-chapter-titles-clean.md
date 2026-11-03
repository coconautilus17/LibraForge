---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner cleans all titles, reviews them and saves.
  entities: []
  contexts:
    web:
      place: web::chapter-forge
- kind: product
  text: The Product changes chapter titles using the cleanup while retaining their timing.
  entities:
  - entity: chapter
    effect: changes
    facts:
    - Title
  contexts:
    web:
      place: web::chapter-forge
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/static/chapter-forge.js#cleanAllTitles
---

# Clean detected labels

## Trigger

Detected labels contain removable spoken wording.

## Outcome

The Product changes chapter titles using the cleanup while retaining their timing.
