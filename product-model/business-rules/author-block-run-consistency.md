---
appliesTo:
- type: capability
  id: preview-book-moves
- type: capability
  id: apply-book-moves
references:
- kind: code
  role: implementation
  target: scripts/organize-audiobooks-by-metadata-v3_13.py#annotate_run_consistency
- kind: code
  role: implementation
  target: scripts/organize-audiobooks-by-metadata-v3_13.py#count_author_folder_moves
- kind: code
  role: implementation
  target: scripts/organize-audiobooks-by-metadata-v3_13.py#render_naming_template_full
---

# Co-written books keep one author folder per run, and doubtful author folders are flagged

Within one run, books by the same set of authors get the order and spelling of the first such book, so they share one folder. A planned move is flagged for review when Audiobookshelf would read its top folder as different authors (with what it would read), when the book has more than four authors, when its author order differs from another book by those authors, and when a co-written book is filed apart from the rest of its series. A run reports how many already-organized books move to another author folder.

## Rationale

Multi-author folders change where many existing books live; the flags and the count let the owner see those changes before applying them.
