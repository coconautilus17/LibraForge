---
entities:
- entity: audible-account
  shows:
  - Name
  - Marketplace
  - Connection
  collects:
  - Name
  - Marketplace
entryPoints:
- web: /settings#accounts
references:
- kind: code
  role: implementation
  target: app/static/settings.html
---

# Accounts

Connect, switch, rename and disconnect the saved Audible accounts the tools share.
