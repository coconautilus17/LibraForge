---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner loads the purchased library.
  entities: []
  contexts:
    web:
      place: web::library
- kind: product
  text: The Product presents audible purchase identities and details for selection.
  entities:
  - entity: audible-purchase
    effect: reads
    facts:
    - Identity
    - Details
  - entity: audible-account
    effect: reads
    facts:
    - Name
    - Marketplace
  contexts:
    web:
      place: web::library
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#library_list
- kind: code
  role: implementation
  target: app/static/downloader.html
---

# Read connected purchases

## Trigger

An Audible account has been connected.

## Outcome

The Product presents audible purchase identities and details for selection.

## Edge cases

- A missing connection or failed Audible request produces an actionable load error.
- One request returns at most 1,000 purchases.
