---
entities:
- entity: audiosilo-settings
  shows:
  - URL
  collects:
  - URL
entryPoints:
- web: /settings#audiosilo
references:
- kind: code
  role: implementation
  target: app/static/settings.html
---

# AudioSilo

The AudioSilo database Metadata Forge searches when Audible finds no confident match.
