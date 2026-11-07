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
  text: The Product starts the Bulk Import scan and records the listing it picks per book from its event stream.
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
  target: dev/benchmark/readmeabook.py
---

# Run ReadMeABook

## Trigger

The owner starts readmeabook.py setup and scan against a throwaway ReadMeABook.

## Outcome

The run's results and run time are saved for the audit.

## Edge cases

- A folder it merges into another counts as nothing picked.
