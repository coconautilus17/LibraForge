---
kind: alternate
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner chooses to remove the login locally only.
  entities: []
  contexts:
    web:
      place: web::accounts
- kind: product
  text: The Product removes the Active audible account locally without claiming the remote device was deregistered.
  entities:
  - entity: audible-account
    effect: removes
    from: Active
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

# Remove a local connection after failed deregistration

## Trigger

The remote deregistration could not complete.

## Outcome

The Product removes the Active audible account locally without claiming the remote device was deregistered.
