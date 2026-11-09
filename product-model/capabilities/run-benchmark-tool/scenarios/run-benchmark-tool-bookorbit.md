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
  text: The Product starts BookOrbit's bulk metadata fetch and records each book's record as fetched.
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
  target: dev/benchmark/bookorbit.py
---

# Run BookOrbit

## Trigger

The owner starts bookorbit.py fetch, then rows, against a throwaway BookOrbit library.

## Outcome

The run's results and run time are saved for the audit.

## Edge cases

- A library fetched before holds BookOrbit's own metadata, so a rerun needs a new library.
