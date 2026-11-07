---
kind: primary
routes:
  cli: Command line
steps:
- kind: actor
  actor: library-owner
  text: The owner checks the dump against the library, imports the books it lacks and removes duplicate searches.
  entities: []
  contexts: &id001
    cli:
      place: cli
- kind: product
  text: The Product adds each new book with what its file name states as its right answer, and keeps one book of
    each identical search.
  entities:
  - entity: benchmark-book
    effect: creates
    facts:
    - Folder
    - File
    - Original tags
    - Runtime
    - Right answer
    - Answer source
    - Origin
  contexts: *id001
  actor: library-owner
references:
- kind: code
  role: implementation
  target: dev/benchmark/overlap.py
- kind: code
  role: implementation
  target: dev/benchmark/collect.py#import_dump
- kind: code
  role: implementation
  target: dev/benchmark/dedupe.py#dedupe
---

# Import another library's books

## Trigger

The owner has an ffprobe dump of another library's files from before any matching.

## Outcome

The dataset holds the books this library lacks, each answered by its file name, with no two books starting the same search.

## Edge cases

- A file name in another form names no right answer: the book is reported, not scored.
- A dumped copy of a library book that starts from different tags comes back as its own search; within 3% of the library book's runtime the library's answer is its answer.
