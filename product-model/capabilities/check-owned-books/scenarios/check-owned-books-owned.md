---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner checks which purchases are already in the library.
  entities: []
  contexts:
    web:
      place: web::library
- kind: product
  text: The Product changes the audible purchase Owned facts from matched ASINs and reports the source of that
    determination.
  entities:
  - entity: audible-purchase
    effect: changes
    facts:
    - Owned
  - entity: audiobook
    effect: reads
    facts:
    - Identifiers
    - Path
  contexts:
    web:
      place: web::library
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#library_owned_asins
- kind: code
  role: implementation
  target: app/main.py#_scan_owned_asins
---

# Identify existing books

## Trigger

The owner chooses a local library root.

## Outcome

The Product changes the audible purchase Owned facts from matched ASINs and reports the source of that determination.

## Edge cases

- Filesystem fallback uses filename ASINs, saved companions and then embedded tags.
- Owned is an ASIN match, not a title-only duplicate guarantee.
