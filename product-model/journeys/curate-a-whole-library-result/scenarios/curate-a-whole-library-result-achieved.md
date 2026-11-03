---
kind: primary
result: achieved
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  capability: browse-whole-library-results
  text: The owner chooses Edit for an enrichment result.
  entities:
  - entity: enrichment-result
    effect: reads
    facts:
    - Subject
    - Genres
    - Evidence
    - Pinned genres
    - Narrator
    - Explicit choices
    - Included books
    - Apply result
  contexts:
    web:
      place: web::whole-library
- kind: product
  actor: library-owner
  capability: browse-whole-library-results
  text: The Product carries the selected enrichment result subject into detailed compilation.
  entities:
  - entity: enrichment-result
    effect: reads
    facts:
    - Subject
  contexts:
    web:
      place: web::enrichment-forge
- kind: product
  actor: library-owner
  capability: compile-enrichment
  text: The Product compiles a fresh enrichment result for that subject.
  entities:
  - entity: enrichment-result
    effect: creates
    facts:
    - Subject
    - Genres
    - Evidence
    - Pinned genres
    - Narrator
    - Explicit choices
    - Included books
    - Apply result
    to: Compiled
  contexts:
    web:
      place: web::enrichment-forge
- kind: actor
  actor: library-owner
  capability: edit-enrichment-result
  text: The owner curates enrichment result fields and included books.
  entities:
  - entity: enrichment-result
    effect: changes
    facts:
    - Genres
    - Narrator
    - Explicit choices
    - Included books
  contexts:
    web:
      place: web::enrichment-forge
- kind: actor
  actor: library-owner
  capability: apply-enrichment
  text: The owner chooses Apply.
  entities: []
  contexts:
    web:
      place: web::enrichment-forge
- kind: product
  actor: library-owner
  capability: apply-enrichment
  text: The Product changes audiobook library fields and marks the enrichment result Applied.
  entities:
  - entity: audiobook
    effect: changes
    facts:
    - Genres
    - Narrator
    - Explicit
  - entity: enrichment-result
    effect: changes
    facts:
    - Apply result
    from: Compiled
    to: Applied
  contexts:
    web:
      place: web::enrichment-forge
references:
- kind: code
  role: implementation
  target: app/static/enrichment-forge.js#renderBatchTable
- kind: code
  role: implementation
  target: app/main.py#enrichment_apply
---

# Curate a whole-library result successfully

## Trigger

A whole-library row needs more than the bulk proposal.

## Outcome

The chosen proposal has been curated and applied to included books.
