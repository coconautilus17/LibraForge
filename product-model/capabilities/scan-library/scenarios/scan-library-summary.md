---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner picks a library folder and scans it.
  entities: []
  contexts:
    web:
      place: web::start-here
- kind: product
  text: The Product reads audiobook and ebook identities and presents counts and book details for the preparation
    stages.
  entities:
  - entity: audiobook
    effect: reads
    facts:
    - Path
    - Title
    - Author
    - Narrator
    - Identifiers
    - Cover
    - Audio
    - Metadata status
  - entity: ebook
    effect: reads
    facts:
    - Path
    - Title
    - Author
    - Series
    - Publication
    - Genres
    - Summary
    - Cover
    - Metadata status
  contexts:
    web:
      place: web::start-here
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#_categorized_book_units
- kind: code
  role: implementation
  target: app/main.py#_categorise_book_unit
---

# Classify an import folder

## Trigger

The owner wants to see what needs attention.

## Outcome

The Product reads audiobook and ebook identities and presents counts and book details for the preparation stages.

## Edge cases

- A complete single M4B under an import subfolder remains ready to organize; scanning the library root can recognize its existing nested organization.
- Ignored folders are excluded, and an empty folder produces empty counts.
