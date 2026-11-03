---
availability:
- place: web
references:
- kind: code
  role: implementation
  target: app/main.py#library_owned_asins
- kind: code
  role: implementation
  target: app/main.py#_scan_owned_asins
domain: library-downloader
---

# Check owned books

Compare purchase ASINs with Audiobookshelf’s indexed library or a cached local scan to flag books already present.
