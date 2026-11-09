---
kind: primary
routes:
  cli: Command line
steps:
- kind: actor
  actor: library-owner
  text: The owner collects the dataset from the library root.
  entities: []
  contexts: &id001
    cli:
      place: cli
- kind: product
  text: The Product writes one benchmark book per book folder whose sidecar kept its original tags and runtime.
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
  target: dev/benchmark/collect.py#collect
---

# Collect the library's books

## Trigger

The owner runs collect.py over the library root.

## Outcome

Every book with saved original tags is in the dataset, those with an applied match carrying it as their right answer.

## Edge cases

- A folder with several audio files is kept only when its backup names the file whose tags were saved.
- The recycle bin and hidden folders are left out; the staging folder is included.
- A book whose applied match has no real ASIN has no right answer and is reported, not scored.
