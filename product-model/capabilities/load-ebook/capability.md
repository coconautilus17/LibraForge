---
availability:
- place: web
references:
- kind: code
  role: implementation
  target: app/main.py#load_manual_review_ebook_target
- kind: code
  role: implementation
  target: app/main.py#match_ebook_unit
domain: metadata-forge
---

# Load ebook

Read a local ebook’s saved fields and find a candidate using its EPUB metadata or filename clues.
