---
kind: edge
routes:
  web: Web
steps:
- kind: actor
  actor: library-owner
  text: The owner starts downloading the selected purchases.
  entities: []
  contexts:
    web:
      place: web::library
- kind: product
  text: The Product records the remaining audible purchase failures without repeatedly requesting grants after
    the threshold is detected.
  entities:
  - entity: audible-purchase
    effect: changes
    facts:
    - Download result
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

# Report an upstream license limit

## Trigger

Audible reports an account license-grant threshold.

## Outcome

The Product records the remaining audible purchase failures without repeatedly requesting grants after the threshold is detected.
