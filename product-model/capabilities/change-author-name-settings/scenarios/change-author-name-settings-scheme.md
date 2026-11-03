---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner switches the universal author-name scheme on or off.
  entities: []
  contexts:
    web:
      place: web::author-names
- kind: product
  text: The Product changes the author name settings Universal scheme without renaming existing audiobook paths.
  entities:
  - entity: author-name-settings
    effect: changes
    facts:
    - Universal scheme
  - entity: audiobook
    effect: reads
    facts:
    - Path
  contexts:
    web:
      place: web::author-names
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#update_author_names_policy
- kind: code
  role: implementation
  target: app/install_state.py#init_install_state
- kind: code
  role: implementation
  target: app/author_names.py#output_author_credit
---

# Change the initials scheme

## Trigger

The owner reviews Author names settings.

## Outcome

The Product changes the author name settings Universal scheme without renaming existing audiobook paths.
