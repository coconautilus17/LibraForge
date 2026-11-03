---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner enters the URL and API key and chooses Save and verify.
  entities: []
  contexts:
    web:
      place: web::audiobookshelf
- kind: product
  text: The Product changes the audiobookshelf settings and reports the connection as reachable when the check
    succeeds.
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

# Save and verify the connection

## Trigger

The owner has an Audiobookshelf service and key.

## Outcome

The Product changes the audiobookshelf settings and reports the connection as reachable when the check succeeds.

## Edge cases

- An empty key or invalid service address is rejected.
