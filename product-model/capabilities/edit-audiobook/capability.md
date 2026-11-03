---
availability:
- place: web
references:
- kind: code
  role: implementation
  target: app/main.py#edit_manual_review_book
- kind: code
  role: implementation
  target: app/main.py#upload_manual_review_cover
- kind: code
  role: implementation
  target: app/static/manual-review-edit.js
domain: metadata-forge
---

# Edit audiobook

Edit a local book’s fields directly without choosing a provider match, including a cover URL or a JPEG/PNG upload. Saving marks the book as manually applied.
