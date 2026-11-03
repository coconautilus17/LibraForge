---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner opens the connected accounts list.
  entities: []
  contexts:
    web:
      place: web::accounts
- kind: product
  text: The Product presents audible account labels and marketplace details with the active account identified.
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
  target: app/main.py#auth_accounts
- kind: code
  role: implementation
  target: app/main.py#_list_accounts
---

# Read saved accounts

## Trigger

The owner opens Accounts.

## Outcome

The Product presents audible account labels and marketplace details with the active account identified.
