---
kind: primary
routes:
  cli: Command line
steps:
- kind: actor
  actor: library-owner
  text: The owner builds the review library, applies the right matches in a throwaway LibraForge and reads them
    back.
  entities: []
  contexts: &id001
    cli:
      place: cli
- kind: product
  text: The Product records each applied listing as the book's right answer, from a confirmed listing.
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
  target: dev/benchmark/review_lib.py
---

# Confirm answers in a review library

## Trigger

Some benchmark books have no confirmed listing.

## Outcome

Every book applied in the review library has that listing as its confirmed right answer.

## Edge cases

- A few answers were confirmed by hand outside the review library; they are kept in the dataset as written.
