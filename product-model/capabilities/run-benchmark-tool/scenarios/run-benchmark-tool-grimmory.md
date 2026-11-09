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
  text: The Product starts Grimmory's metadata refresh with Audible first over the iTunes mock and records each
    book's fields.
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
  target: dev/benchmark/grimmory.py
---

# Run Grimmory

## Trigger

The owner starts grimmory.py setup, library, refresh and rows against a throwaway Grimmory.

## Outcome

The run's results and run time are saved for the audit.
