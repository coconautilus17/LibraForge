---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner activates another saved account.
  entities: []
  contexts:
    web:
      place: web::accounts
- kind: product
  text: The Product changes the selected audible account from Inactive to Active and the former selection from
    Active to Inactive.
  entities:
  - entity: audible-account
    effect: changes
    facts:
    - Connection
    from: Inactive
    to: Active
    as: selected
  - entity: audible-account
    effect: changes
    facts:
    - Connection
    from: Active
    to: Inactive
    as: previous
  contexts:
    web:
      place: web::accounts
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#auth_account_activate
---

# Select another account

## Trigger

At least two saved accounts exist.

## Outcome

The Product changes the selected audible account from Inactive to Active and the former selection from Active to Inactive.

## Edge cases

- An unknown saved account cannot be activated.
