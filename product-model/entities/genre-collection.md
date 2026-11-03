---
domain: enrichment-forge
references:
- kind: code
  role: implementation
  target: app/genre_collections.py
---

# Genre collection

An Audiobookshelf collection for books sharing a library genre.

## Information kept

- **Name** — Genre used as the collection name, numbered when a large genre is split into parts.
- **Library** — Audiobookshelf library containing the collection.
- **Books** — Current book membership.
- **Managed by LibraForge** — Whether LibraForge created and marked the collection.
