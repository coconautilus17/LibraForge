---
kind: edge
routes:
  web: Web
  cli: Command line
steps:
- kind: actor
  actor: library-owner
  text: The owner starts matching.
  entities: []
  contexts:
    web:
      place: web::metadata-forge
    cli:
      place: cli
- kind: product
  text: The Product marks the metadata match Audible unavailable, tries no later source for that book and
    plans no write for it.
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
  contexts:
    web:
      place: web::metadata-forge
    cli:
      place: cli
  actor: library-owner
---

# Distinguish an unreachable Audible from no match

## Trigger

Audible keeps refusing or failing a book's lookups after the Product has waited for it.

## Outcome

The book is marked Audible unavailable, no fallback source is tried for it, and nothing is written for it in that run.
