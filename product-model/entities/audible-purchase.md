---
domain: library-downloader
references:
- kind: code
  role: implementation
  target: app/main.py#_library_item_to_dict
- kind: code
  role: implementation
  target: app/main.py#run_download_worker
---

# Audible purchase

A title in the connected Audible account’s purchased library.

## Information kept

- **Identity** — ASIN, title, author, narrator and series.
- **Details** — Cover, duration and purchase information.
- **Owned** — Whether a matching ASIN is already in the local library.
- **Duplicate action** — Keep both or replace for a selected download.
- **Download result** — Output location, completion or failure.
