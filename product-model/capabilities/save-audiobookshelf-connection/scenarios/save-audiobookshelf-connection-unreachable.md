---
kind: edge
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner saves the URL and API key.
  entities: []
  contexts:
    web:
      place: web::audiobookshelf
- kind: product
  text: The Product saves the audiobookshelf settings and reports Reachable as false so the owner can correct
    the connection.
  entities:
  - entity: audiobookshelf-settings
    effect: changes
    facts:
    - URL
    - Key configured
    - Key source
    - Reachable
    - API key
  contexts:
    web:
      place: web::audiobookshelf
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#abs_save_config
---

# Keep an unverified saved connection

## Trigger

The verification request cannot reach the service.

## Outcome

The Product saves the audiobookshelf settings and reports Reachable as false so the owner can correct the connection.
