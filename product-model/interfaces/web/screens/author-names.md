---
entities:
- entity: author-name-settings
  shows:
  - Universal scheme
  - Origin
  - Notice pending
  collects:
  - Universal scheme
- entity: author-name-pattern
  shows:
  - Name
  - Spelling
  - Origin
  - Enabled
  collects:
  - Name
  - Spelling
entryPoints:
- web: /settings#author-names
references:
- kind: code
  role: implementation
  target: app/static/settings.html
---

# Author names

Switch the universal initials scheme and keep spelling exceptions it must leave alone.
