---
kind: primary
routes:
  cli: Command line
steps:
- kind: actor
  actor: library-owner
  text: The owner asks for the record of every confirmed listing.
  entities: []
  contexts: &id001
    cli:
      place: cli
- kind: product
  text: The Product reads each confirmed listing from the catalog by its ASIN and records the listing's whole
    record as the book's right answer.
  entities:
  - entity: benchmark-book
    effect: changes
    facts:
    - Right answer
  contexts: *id001
  actor: library-owner
references:
- kind: code
  role: implementation
  target: dev/benchmark/answers.py#records
---

# Read the right answers from the catalog

## Trigger

Books were confirmed, or the dataset is being prepared for an audit.

## Outcome

Every book with a confirmed listing has that listing's complete record as its right answer.

## Edge cases

- A listing the catalog no longer returns keeps no record; its book is reported, not scored, until another listing is confirmed.
- A confirmed listing found by hand to be another book or another recording is removed, or replaced by the file's own recording's listing; a book left without one is reported, not scored.
