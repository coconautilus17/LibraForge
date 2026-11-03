---
kind: alternate
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner removes an inactive saved account.
  entities: []
  contexts:
    web:
      place: web::accounts
- kind: product
  text: The Product deregisters and removes the Inactive audible account connection.
  entities:
  - entity: audible-account
    effect: removes
    from: Inactive
  contexts:
    web:
      place: web::accounts
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#auth_disconnect
- kind: code
  role: implementation
  target: app/main.py#auth_account_remove
- kind: code
  role: implementation
  target: app/main.py#_deregister_or_502
---

# Remove an inactive account

## Trigger

An inactive saved connection is no longer needed.

## Outcome

The Product deregisters and removes the Inactive audible account connection.
