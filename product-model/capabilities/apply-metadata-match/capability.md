---
availability:
- place: web
references:
- kind: code
  role: implementation
  target: app/main.py#apply_manual_review_result
- kind: code
  role: implementation
  target: app/main.py#_write_book_metadata
- kind: code
  role: implementation
  target: app/static/app.js
domain: metadata-forge
---

# Apply metadata match

Apply an explicitly selected match in Full metadata or Series only mode after reviewing the editable fields. Apply Fill preserves blank inputs; Full Overwrite can clear fields supported by the writer.
