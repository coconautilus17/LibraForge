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
  text: The Product applies Quick Match to every book, one at a time, and records the listing each took.
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
  target: dev/benchmark/abs_quickmatch.py
---

# Run Audiobookshelf Quick Match

## Trigger

The owner starts abs_quickmatch.py against a throwaway Audiobookshelf.

## Outcome

The run's results and run time are saved for the audit.
