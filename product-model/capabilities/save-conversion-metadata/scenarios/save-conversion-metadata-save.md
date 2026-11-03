---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner saves the reviewed conversion metadata.
  entities: []
  contexts:
    web:
      place: web::m4b-tool
- kind: product
  text: The Product changes the audiobook Conversion metadata and associated companion artifact for later conversion.
  entities:
  - entity: audiobook
    effect: changes
    facts:
    - Conversion metadata
    - Companions
  contexts:
    web:
      place: web::m4b-tool
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#save_m4b_metadata
- kind: code
  role: implementation
  target: app/main.py#save_sidecar_file
---

# Keep metadata for conversion

## Trigger

The conversion form has been reviewed.

## Outcome

The Product changes the audiobook Conversion metadata and associated companion artifact for later conversion.
