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
  text: The Product imports every book quietly with the audible plugin, given each book's real runtime, and records
    the books beets accepted.
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
  target: dev/benchmark/beets_run.sh
- kind: code
  role: implementation
  target: dev/benchmark/beets_rows.py
---

# Run beets

## Trigger

The owner starts beets_run.sh over the iTunes mock.

## Outcome

The run's results and run time are saved for the audit.
