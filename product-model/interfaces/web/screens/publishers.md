---
entities:
- entity: publisher
  shows:
  - Name
  - Special provider
  - Origin
  - Enabled
  collects:
  - Name
  - Special provider
  - Enabled
entryPoints:
- web: /settings#publishers
references:
- kind: code
  role: implementation
  target: app/static/settings.html
---

# Publishers

Publishers in use, custom publishers and publishers learned during runs, each switched on or off.
