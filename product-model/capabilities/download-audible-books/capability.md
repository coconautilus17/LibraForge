---
availability:
- place: web
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
domain: library-downloader
---

# Download Audible books

Download selected purchases to standard M4B with embedded metadata, chapters, cover and ASIN; per-book duplicate choices override the run default.
