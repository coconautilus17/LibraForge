---
kind: primary
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner chooses a destination folder and downloads the selected books.
  entities: []
  contexts:
    web:
      place: web::library
- kind: product
  text: The Product creates audiobook M4B outputs and records each audible purchase Download result, completing
    the run.
  entities:
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
    to: Completed
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

# Download selected purchases

## Trigger

An Audible account and purchases are selected.

## Outcome

The Product creates audiobook M4B outputs and records each audible purchase Download result, completing the run.

## Edge cases

- Keep both uses a suffixed destination when the computed target folder exists; Replace replaces that target folder.
- The optional organize pass previews then applies moves after successful downloads.
