---
entities:
- entity: library-preferences
  shows:
  - Default root
  - Organizer scan root
  - Ignored folders
  - Skip patterns
  collects:
  - Default root
  - Organizer scan root
  - Ignored folders
  - Skip patterns
entryPoints:
- web: /settings#library
references:
- kind: code
  role: implementation
  target: app/static/settings.html
---

# Library

Default folders, ignored folder names and persistent skip patterns, kept in this browser.
