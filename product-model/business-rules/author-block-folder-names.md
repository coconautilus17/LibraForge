---
appliesTo:
- type: capability
  id: preview-naming-template
- type: capability
  id: preview-book-moves
- type: capability
  id: apply-book-moves
references:
- kind: code
  role: implementation
  target: scripts/organize-audiobooks-by-metadata-v3_13.py#find_author_block
- kind: code
  role: implementation
  target: scripts/organize-audiobooks-by-metadata-v3_13.py#author_block_people
- kind: code
  role: implementation
  target: scripts/organize-audiobooks-by-metadata-v3_13.py#render_naming_template_full
- kind: code
  role: implementation
  target: app/abs_names.py#parse_name_string
---

# An author block names a co-written book's authors the way Audiobookshelf reads them back

A naming template's author block marked `{+}` names every author of the book, joined by the separator chosen between authors and the one chosen before the last author; only separator pairs Audiobookshelf can split are accepted. At most four authors are named, followed by "et al". Role credits (translator, foreword and the like) and generic credits are left out; ";" credits, last-first credits ("Holt, Mara") and a trailing "et al" or "others" are read the way Audiobookshelf splits a credit. Each name is written whole or in parts (first name, last name, initials), split the way Audiobookshelf splits a name. Initials are written closed up ("J.R.R."), unless the owner chooses that initials follow the author-name scheme, which has an effect only while that scheme is on. `{+}` is accepted only in the first author block. A template without `{+}` names folders exactly as before.

## Rationale

Audiobookshelf reads the top folder as the book's authors when tags name none, so a folder it would split differently creates wrong authors. Keeping initials in one form avoids several folders for the same author.
