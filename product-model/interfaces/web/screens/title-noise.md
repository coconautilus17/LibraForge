---
entities:
- entity: title-noise-pattern
  shows:
  - Label
  - Pattern
  - Origin
  - Enabled
  collects:
  - Label
  - Pattern
  - Enabled
entryPoints:
- web: /settings#title-noise
references:
- kind: code
  role: implementation
  target: app/static/settings.html
---

# Title noise

Marketing phrases removed from titles before matching and organizing, shipped or custom.
