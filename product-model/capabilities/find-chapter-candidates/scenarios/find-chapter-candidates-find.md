---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner searches the selected folder.
  entities: []
  contexts:
    web:
      place: web::chapter-forge
- kind: product
  text: The Product presents single-file MP3 audiobook candidates with their paths and size.
  entities:
  - entity: audiobook
    effect: reads
    facts:
    - Path
    - Audio
  contexts:
    web:
      place: web::chapter-forge
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#chaptering_candidates
---

# Find a candidate for chapter detection

## Trigger

The owner needs a book to chapter.

## Outcome

The Product presents single-file MP3 audiobook candidates with their paths and size.
