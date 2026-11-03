---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner inserts a row, corrects its start time and saves.
  entities: []
  contexts:
    web:
      place: web::chapter-forge
- kind: product
  text: The Product creates the chapter entry with its title and timing in the saved list.
  entities:
  - entity: chapter
    effect: creates
    facts:
    - Title
    - Timing
    - Evidence
    - Manual
  contexts:
    web:
      place: web::chapter-forge
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/static/chapter-forge.js#addChapter
- kind: code
  role: implementation
  target: app/static/chapter-forge.js#insertChapterAfter
- kind: code
  role: implementation
  target: app/main.py#save_chaptering
---

# Insert a missing chapter

## Trigger

The existing list omits a boundary.

## Outcome

The Product creates the chapter entry with its title and timing in the saved list.
