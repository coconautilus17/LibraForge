---
kind: alternate
routes:
  cli: Command line
steps:
- kind: product
  text: The Product lists, for each book with no confirmed listing, the listings the tools chose whose record
    agrees with the author, book number and title its file name states.
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
  text: The owner confirms or rejects each candidate by hand.
  entities: []
  contexts: *id001
- kind: product
  text: The Product records each confirmed candidate as the book's listing, confirmed by hand.
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

Every candidate the owner confirmed is its book's listing; the rest stay without a right answer.

## Edge cases

- A book with no candidate, or only rejected ones, stays reported, not scored.
- A candidate is offered whichever tool chose it; confirming it is the owner's call, never a tool's.
