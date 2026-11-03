---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner searches a provider from M4B Tool.
  entities: []
  contexts:
    web:
      place: web::m4b-tool
- kind: product
  text: The Product presents metadata match candidates whose selected values can fill the audiobook conversion
    form.
  entities:
  - entity: metadata-match
    effect: creates
    facts:
    - Book
    - Candidate
    - Provider
    - Score
    - Edit mode
    - Review reasons
    - Write outcome
  - entity: audiobook
    effect: reads
    facts:
    - Title
    - Author
  contexts:
    web:
      place: web::m4b-tool
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#search_audible_candidates
- kind: code
  role: implementation
  target: app/main.py#search_abs_candidates
- kind: code
  role: implementation
  target: app/main.py#search_abs_agg_candidates
- kind: code
  role: implementation
  target: app/main.py#search_abs_tract_candidates
- kind: code
  role: implementation
  target: app/static/m4b-tool.js
---

# Find conversion metadata

## Trigger

The owner is preparing a conversion.

## Outcome

The Product presents metadata match candidates whose selected values can fill the audiobook conversion form.
