---
entities:
- entity: audiobook
  shows:
  - Path
  - Title
  - Author
  - Cover
  - Audio
  - Metadata status
- entity: ebook
  shows:
  - Path
  - Title
  - Author
  - Metadata status
entryPoints:
- web: /
references:
- kind: code
  role: implementation
  target: app/main.py#scan_books_route
---

# Start Here

Assess the selected library folder and the next preparation work.
