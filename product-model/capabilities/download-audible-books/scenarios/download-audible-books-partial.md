---
kind: edge
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner downloads the selected purchases.
  entities: []
  contexts:
    web:
      place: web::library
- kind: product
  text: The Product records audible purchase successes and failures in selection order and completes the run
    with errors while retaining successful audiobook outputs.
  entities:
  - entity: audible-purchase
    effect: changes
    facts:
    - Download result
  - entity: run
    effect: creates
    facts:
    - Tool
    - Target
    - Options
    - Progress
    - Results
    - Timing
    to: Completed with errors
  - entity: audiobook
    effect: creates
    facts:
    - Path
    - Title
    - Author
    - Narrator
    - Series
    - Identifiers
    - Cover
    - Audio
  contexts:
    web:
      place: web::library
  actor: library-owner
references:
- kind: code
  role: implementation
  target: app/main.py#run_download_worker
- kind: code
  role: implementation
  target: app/main.py#start_library_download
- kind: code
  role: implementation
  target: app/static/downloader.html
---

# Keep a complete per-title download report

## Trigger

Some selected titles cannot be downloaded or converted.

## Outcome

The Product records audible purchase successes and failures in selection order and completes the run with errors while retaining successful audiobook outputs.
