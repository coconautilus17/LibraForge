---
entities:
- entity: goodreads-settings
  shows:
  - URL
  - Kindle region
  collects:
  - URL
  - Kindle region
entryPoints:
- web: /settings#abs-tract
references:
- kind: code
  role: implementation
  target: app/static/settings.html
---

# Goodreads / Kindle

The abs-tract address and Kindle region used for Kindle cover lookups.
