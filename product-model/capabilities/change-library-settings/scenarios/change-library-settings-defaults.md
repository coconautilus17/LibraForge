---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner changes the library preferences.
  entities:
  - entity: library-preferences
    effect: reads
    facts:
    - Default root
    - Organizer scan root
    - Ignored folders
    - Skip patterns
  contexts:
    web:
      place: web::library-settings
- kind: product
  text: The Product changes library preferences for subsequent supported scans and processing in this browser.
  entities:
  - entity: library-preferences
    effect: changes
    facts:
    - Default root
    - Organizer scan root
    - Ignored folders
    - Skip patterns
  contexts:
    web:
      place: web::library-settings
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/static/ui-preferences.js
---

# Save library defaults

## Trigger

The owner wants recurring folder choices.

## Outcome

The Product changes library preferences for subsequent supported scans and processing in this browser.

## Edge cases

- An empty organizer scan root falls back to the built-in import folder.
- Persistent skip patterns join a metadata run only when the inclusion option is selected.
