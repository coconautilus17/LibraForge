---
references:
- kind: code
  role: implementation
  target: app/main.py#load_manual_review_ebook_target
- kind: code
  role: implementation
  target: app/main.py#apply_manual_review_ebook_target
- kind: code
  role: implementation
  target: app/library_index.py
---

# Ebook

An ebook identity with one or more paired formats, reviewed separately from audio.

## Information kept

- **Path** — Location and paired EPUB or PDF formats.
- **Title** — Title and subtitle.
- **Author** — Author credits.
- **Series** — Series and sequence.
- **Publication** — Publication year and ISBN.
- **Genres** — Book genres.
- **Summary** — Description.
- **Cover** — Selected cover reference.
- **Metadata status** — The locally saved book metadata and matching result.
