---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner enters the address of their own AudioSilo database, or clears it, and saves.
  entities: []
  contexts:
    web:
      place: web::audiosilo
- kind: product
  text: The Product keeps the address, or the public service when it was cleared, and reports
    whether the database answers.
  entities:
  - entity: audiosilo-settings
    effect: changes
    facts:
    - URL
  contexts:
    web:
      place: web::audiosilo
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#save_audiosilo_settings
- kind: code
  role: implementation
  target: app/main.py#audiosilo_health
---

# Point Metadata Forge at an AudioSilo database

## Trigger

The owner runs a copy of AudioSilo's database, or wants the public service back.

## Outcome

The Product keeps the address, or the public service when it was cleared, and reports whether the database answers.
