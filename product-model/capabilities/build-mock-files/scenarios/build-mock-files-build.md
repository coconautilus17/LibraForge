---
kind: primary
routes:
  cli: Command line
steps:
- kind: actor
  actor: library-owner
  text: The owner builds the mock in the format the tool reads.
  entities: []
  contexts: &id001
    cli:
      place: cli
- kind: product
  text: The Product writes one silent file per benchmark book with its original tags at its folder path.
  entities:
  - entity: benchmark-book
    effect: reads
    facts:
    - Folder
    - File
    - Original tags
    - Runtime
  contexts: *id001
  actor: library-owner
references:
- kind: code
  role: implementation
  target: dev/benchmark/bo_mock.py
---

# Build a mock library

## Trigger

A tool other than LibraForge is about to run.

## Outcome

A folder of silent files, one per book, carries each book's original tags at its folder path.

## Edge cases

- Custom tag keys for ffprobe readers, iTunes atoms for mutagen and jaudiotagger readers.
- As long as the book for a tool that checks runtime.
- Public: only the tags a matcher reads, for the downloadable mock.
