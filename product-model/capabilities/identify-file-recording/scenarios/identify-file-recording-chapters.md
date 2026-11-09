---
kind: primary
routes:
  cli: Command line
steps:
- kind: actor
  actor: library-owner
  text: The owner compares the book's audio with the candidate listings.
  entities: []
  contexts: &id001
    cli:
      place: cli
- kind: product
  text: The Product counts, per listing, the parts of the audio whose lengths agree with the file's within the tolerance.
  entities:
  - entity: benchmark-book
    effect: reads
    facts:
    - File
    - Right answer
  contexts: *id001
  actor: library-owner
references:
- kind: code
  role: implementation
  target: dev/tools/chapter_match.py
---

# Match a file's chapters to a listing

## Trigger

Tags and runtime disagree on which recording a file is.

## Outcome

The listing whose chapter lengths agree with the file's is named.
