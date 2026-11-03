---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner adds or removes genre chips, includes or excludes books and sets narrator or explicit choices.
  entities: []
  contexts:
    web:
      place: web::enrichment-forge
- kind: product
  text: The Product changes the enrichment result selections without changing audiobook metadata until Apply.
  entities:
  - entity: enrichment-result
    effect: changes
    facts:
    - Genres
    - Narrator
    - Explicit choices
    - Included books
  - entity: audiobook
    effect: reads
    facts:
    - Genres
    - Narrator
    - Explicit
  contexts:
    web:
      place: web::enrichment-forge
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/static/enrichment-forge.js#addGenreChip
- kind: code
  role: implementation
  target: app/static/enrichment-forge.js#renderBookList
---

# Curate the proposal

## Trigger

A compiled result is open.

## Outcome

The Product changes the enrichment result selections without changing audiobook metadata until Apply.

## Edge cases

- Typed main genre names are classified as main genres; existing pins remain identifiable.
- A per-book explicit choice overrides the series-wide choice.
