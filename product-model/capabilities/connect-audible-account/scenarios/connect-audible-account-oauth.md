---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner enters an account name and marketplace, signs in on Amazon and pastes back the redirect URL.
  entities: []
  contexts:
    web:
      place: web::accounts
- kind: product
  text: The Product saves an Active audible account and makes it the current shared selection.
  entities:
  - entity: audible-account
    effect: creates
    facts:
    - Name
    - Marketplace
    - Connection
    to: Active
  contexts:
    web:
      place: web::accounts
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#auth_login_start
- kind: code
  role: implementation
  target: app/main.py#auth_login_complete
---

# Connect through Audible

## Trigger

The owner wants another Audible connection.

## Outcome

The Product saves an Active audible account and makes it the current shared selection.

## Edge cases

- A name and supported marketplace are required before generating the sign-in request.
- A missing pending request, invalid returned URL or failed registration is reported without claiming success.
