---
kind: alternate
routes:
  cli: Command line
steps:
- kind: actor
  actor: library-owner
  text: The owner starts the tool over the dataset.
  entities: []
  contexts: &id001
    cli:
      place: cli
- kind: product
  text: The Product starts AudioSilo's Match automatically over the runtime-length mock and records each book as
    confident, to review or not found.
  entities:
  - entity: benchmark-book
    effect: reads
    facts:
    - Folder
    - Original tags
    - Runtime
  - entity: benchmark-run
    effect: creates
    facts:
    - Tool
    - Settings
    - Results
    - Run time
  contexts: *id001
  actor: library-owner
references:
- kind: code
  role: implementation
  target: dev/benchmark/audiosilo.py
---

# Run AudioSilo

## Trigger

The owner starts audiosilo.py library, match and rows against a throwaway AudioSilo in mirror mode.

## Outcome

The run's results and run time are saved for the audit.

## Edge cases

- Before version 2.6, a book whose tags carry an ASIN or ISBN is matched at scan and recorded as its own; from 2.6 those tags are hints its match run checks.
- From 2.6 a match can name only an ISBN or the community's own entry for the book; it is recorded as that match.
