---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner enters a naming template and previews examples.
  entities: []
  contexts:
    web:
      place: web::folder-forge
- kind: product
  text: The Product shows the resulting audiobook and ebook destination names without moving them.
  entities:
  - entity: audiobook
    effect: reads
    facts:
    - Title
    - Author
    - Series
    - Identifiers
    - Path
  - entity: ebook
    effect: reads
    facts:
    - Title
    - Author
    - Series
    - Path
  contexts:
    web:
      place: web::folder-forge
  actor: library-owner
references:
- kind: code
  role: implementation
  target: scripts/organize-audiobooks-by-metadata-v3_13.py#validate_naming_template
- kind: code
  role: implementation
  target: scripts/organize-audiobooks-by-metadata-v3_13.py#preview_naming_template_for_root
- kind: code
  role: implementation
  target: app/main.py#preview_organizer_naming_template_examples
---

# Preview a naming scheme

## Trigger

The owner wants a custom destination layout.

## Outcome

The Product shows the resulting audiobook and ebook destination names without moving them.

## Edge cases

- An invalid or unknown token is reported before the custom scheme is used.
- The built-in scheme ignores the custom template field.
