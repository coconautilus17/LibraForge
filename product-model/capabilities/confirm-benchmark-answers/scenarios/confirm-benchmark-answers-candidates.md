---
kind: alternate
routes:
  cli: Command line
steps:
- kind: product
  text: The Product lists, for each book with no confirmed edition, every edition the tools chose, with its
    record or the fields the tool left, how far it agrees with the book's file name and runtime, and what the
    book's opening credits say of it.
  entities:
  - entity: benchmark-book
    effect: reads
    facts:
    - Folder
    - File
    - Original tags
    - Runtime
  - entity: benchmark-run
    effect: reads
    facts:
    - Results
  contexts: &id001
    cli:
      place: cli
  actor: library-owner
- kind: actor
  actor: library-owner
  text: The owner confirms a candidate as it is, corrects its fields, types the right fields in when no
    candidate fits, or leaves the book without an answer.
  entities: []
  contexts: *id001
- kind: product
  text: The Product records each confirmed edition, with the owner's fields, as the book's right answer,
    confirmed by hand.
  entities:
  - entity: benchmark-book
    effect: changes
    facts:
    - Right answer
    - Answer source
  contexts: *id001
  actor: library-owner
references:
- kind: code
  role: implementation
  target: dev/benchmark/answers.py#candidates
---

# Confirm answers from candidates

## Trigger

Books from another library have no confirmed listing.

## Outcome

Every edition the owner confirmed or typed in is its book's right answer; the rest stay without one.

## Edge cases

- A book with no candidate, or only rejected ones, stays reported, not scored.
- A candidate is offered whichever tool chose it; confirming it is the owner's call, never a tool's.
- Tools that chose the same edition by different means (one by its ISBN, one by the fields it left) are offered as one candidate when they carry the same ID.
- An edition with no ID anywhere is answered by the owner's fields alone; every tool's choice for that book is judged by hand.
