---
availability:
- place: web
references:
- kind: code
  role: implementation
  target: app/main.py#discover_m4b_candidates
- kind: code
  role: implementation
  target: app/conversion_discovery.py#conversion_candidate
domain: m4b-tool
---

# Discover conversion sources

Find recognized multipart books or audio not already in M4B format. Cached discovery is reusable only while the root and matching-script identity remain current.
