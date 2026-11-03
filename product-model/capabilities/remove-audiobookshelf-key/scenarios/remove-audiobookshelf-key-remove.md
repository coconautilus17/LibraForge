---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner chooses Remove key.
  entities: []
  contexts:
    web:
      place: web::audiobookshelf
- kind: product
  text: The Product clears the saved key from audiobookshelf settings and reports whether a deployment-provided
    key remains.
  entities:
  - entity: audiobookshelf-settings
    effect: changes
    facts:
    - Key configured
    - Key source
    - API key
  contexts:
    web:
      place: web::audiobookshelf
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#abs_disconnect
---

# Remove a saved key

## Trigger

The connection has a saved key.

## Outcome

The Product clears the saved key from audiobookshelf settings and reports whether a deployment-provided key remains.
