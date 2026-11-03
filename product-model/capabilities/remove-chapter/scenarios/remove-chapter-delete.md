---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner deletes a row and saves the list.
  entities: []
  contexts:
    web:
      place: web::chapter-forge
- kind: product
  text: The Product removes the chapter from the saved book boundaries.
  entities:
  - entity: chapter
    effect: removes
  contexts:
    web:
      place: web::chapter-forge
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/static/chapter-forge.js#renderChapters
- kind: code
  role: implementation
  target: app/main.py#save_chaptering
---

# Remove a false boundary

## Trigger

A candidate is not a real chapter.

## Outcome

The Product removes the chapter from the saved book boundaries.

## Edge cases

- The immediate editor undo action can restore the deleted row before saving.
