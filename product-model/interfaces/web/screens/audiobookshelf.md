---
entities:
- entity: audiobookshelf-settings
  shows:
  - URL
  - Key configured
  - Key source
  - Reachable
  collects:
  - URL
  - API key
entryPoints:
- web: /settings#absSection
references:
- kind: code
  role: implementation
  target: app/static/settings.html
---

# Audiobookshelf

Save, verify and remove the Audiobookshelf connection used for lookups, owned-book checks and metadata writes.
