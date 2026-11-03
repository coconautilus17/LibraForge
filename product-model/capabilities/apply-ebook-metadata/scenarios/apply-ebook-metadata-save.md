---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner chooses Apply for the corrected ebook fields.
  entities:
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
      place: web::manual-review
- kind: product
  text: The Product saves the ebook metadata and synchronizes the corresponding known Audiobookshelf record;
    unknown items retain local metadata for later use.
  entities:
  - entity: ebook
    effect: changes
    facts:
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
      place: web::manual-review
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#apply_manual_review_ebook_target
---

# Apply an ebook correction

## Trigger

The owner has reviewed the ebook fields.

## Outcome

The Product saves the ebook metadata and synchronizes the corresponding known Audiobookshelf record; unknown items retain local metadata for later use.

## Edge cases

- This operation does not rewrite EPUB contents or manufacture an Audible audiobook ASIN.
