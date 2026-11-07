---
kind: primary
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
  text: The Product feeds each book's original tags, folder and runtime straight into LibraForge's real matcher,
    with no files, and records each report item.
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
  target: dev/benchmark/run.sh
- kind: code
  role: implementation
  target: dev/benchmark/lf_bench.py
---

# Run LibraForge

## Trigger

The owner starts run.sh over the dataset (GOODREADS=1 for the fallback).

## Outcome

The run's results and run time are saved for the audit.

## Edge cases

- CODE= runs another checkout's matcher on the same books, to compare versions.
