---
singleton: true
domain: metadata-forge
references:
- kind: code
  role: implementation
  target: app/audiobook_guild.py#store_catalog
- kind: code
  role: implementation
  target: app/audiobook_guild.py#search_books
- kind: code
  role: implementation
  target: app/data/audiobook-guild-catalog.json
- kind: doc
  role: context
  target: docs/developer/architecture.md
---

# Audiobook Guild catalog

The Audiobook Guild store's books, kept locally so a book by one of its authors is matched without asking the store each time. A new install starts from the copy that ships with LibraForge.

## Information kept

- **Books** — Each book's title, series and number, authors, narrators, description and cover.
- **Runtimes** — Each book's runtime, kept once read, since a published book's runtime never changes.
- **Read at** — When the store was last read; a catalog older than a week is read again before it is used.
