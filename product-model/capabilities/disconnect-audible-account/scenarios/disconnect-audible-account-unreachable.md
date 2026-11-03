---
kind: edge
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner chooses Disconnect.
  entities: []
  contexts:
    web:
      place: web::accounts
- kind: product
  text: The Product retains the audible account and presents retry or an explicitly chosen local-only removal.
  entities:
  - entity: audible-account
    effect: reads
    facts:
    - Name
    - Marketplace
    - Connection
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

# Keep a failed deregistration visible

## Trigger

Audible cannot complete deregistration.

## Outcome

The Product retains the audible account and presents retry or an explicitly chosen local-only removal.
