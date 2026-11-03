---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner enters and saves a new account name.
  entities: []
  contexts:
    web:
      place: web::accounts
- kind: product
  text: The Product changes the audible account Name and retains its connection and marketplace.
  entities:
  - entity: audible-account
    effect: changes
    facts:
    - Name
  contexts:
    web:
      place: web::accounts
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#auth_account_rename
---

# Rename a saved connection

## Trigger

An account label is unclear.

## Outcome

The Product changes the audible account Name and retains its connection and marketplace.

## Edge cases

- Whitespace-only names are rejected; labels are limited to 80 characters.
