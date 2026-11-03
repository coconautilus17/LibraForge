---
kind: alternate
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner completes sign-in for another named account.
  entities: []
  contexts:
    web:
      place: web::accounts
- kind: product
  text: The Product creates the new Active audible account and changes the previous audible account to Inactive.
  entities:
  - entity: audible-account
    effect: creates
    facts:
    - Name
    - Marketplace
    - Connection
    to: Active
    as: new
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
  target: app/main.py#auth_login_start
- kind: code
  role: implementation
  target: app/main.py#auth_login_complete
---

# Connect another account as the active selection

## Trigger

A previously connected account is Active.

## Outcome

The Product creates the new Active audible account and changes the previous audible account to Inactive.
