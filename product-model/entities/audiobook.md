---
relations:
- entity: chapter
  verb: has
  cardinality: one-to-many
references:
- kind: code
  role: implementation
  target: app/main.py#inspect_manual_review_target
- kind: code
  role: implementation
  target: scripts/audible-metadata-fixer-v5.py#build_processing_items
- kind: code
  role: implementation
  target: scripts/audible-metadata-fixer-v5.py#write_marker
---

# Audiobook

A local book, represented by one audio file or a recognized group of chapter or part files.

## Information kept

- **Path** — The book location and the files belonging to it.
- **Title** — Book title and subtitle.
- **Author** — Author credits.
- **Narrator** — Narration credits.
- **Series** — Series names and sequence numbers.
- **Publication** — Year, publisher and language.
- **Identifiers** — Audible ASIN and other available book identifiers.
- **Genres** — Real library genres.
- **Explicit** — The explicit-content flag.
- **Summary** — Description of the book.
- **Cover** — Current cover and a selected replacement.
- **Audio** — Formats, duration, codec, bitrate, sample rate and channels.
- **Metadata status** — Current completeness, matching provenance and whether a human applied it.
- **Original metadata** — Saved original tags available for restoration.
- **Conversion metadata** — Saved title, credits, series, year, summary, cover and ASIN for an M4B output.
- **Companions** — Associated local metadata, cover and chapter artifacts.
