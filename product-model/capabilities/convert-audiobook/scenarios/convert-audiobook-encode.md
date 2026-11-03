---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner starts conversion with the chosen encoding and metadata.
  entities: []
  contexts:
    web:
      place: web::m4b-tool
- kind: product
  text: The Product creates the output audiobook with merged audio and enforced metadata, preserves source
    media and completes the run.
  entities:
  - entity: audiobook
    effect: creates
    facts:
    - Path
    - Title
    - Author
    - Narrator
    - Series
    - Publication
    - Identifiers
    - Genres
    - Summary
    - Cover
    - Audio
  - entity: run
    effect: creates
    facts:
    - Tool
    - Target
    - Options
    - Progress
    - Results
    - Timing
    to: Completed
  contexts:
    web:
      place: web::m4b-tool
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#build_m4b_command
- kind: code
  role: implementation
  target: app/main.py#resolve_m4b_input_files
- kind: code
  role: implementation
  target: app/main.py#run_m4b_worker
---

# Create a merged M4B

## Trigger

The source and output have been reviewed.

## Outcome

The Product creates the output audiobook with merged audio and enforced metadata, preserves source media and completes the run.

## Edge cases

- The output file is excluded from directory inputs; an identical file input and output is rejected.
- Existing user cuesheets are preserved. A saved Chapter Forge result can supply chapters for a single-file conversion.
- Unsupported encoding choices or no remaining source files fail with a specific error.
