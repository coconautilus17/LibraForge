---
domain: enrichment-forge
references:
- kind: code
  role: implementation
  target: app/enrichment.py#compile_series_enrichment
- kind: code
  role: implementation
  target: app/enrichment_batch.py
---

# Enrichment result

A compiled proposal for one series or standalone book, with the evidence needed to curate it.

## Information kept

- **Subject** — Series or standalone identity and member books.
- **Genres** — Main genres, subgenres, suggestions and current genres.
- **Evidence** — Per-book source labels, votes, genre conflicts between sources, source failures and rate limits.
- **Pinned genres** — Genres recognized as the owner’s own choices.
- **Narrator** — Found narrators and an optional shared selection.
- **Explicit choices** — Evidence and per-book explicit, not-explicit or unchanged decisions.
- **Included books** — Which audio books the owner includes.
- **Apply result** — Applied genres and per-book failures.

## States

### Pending

Waiting to compile.

### Compiled

Ready for review.

### Failed

Compilation failed.

### Applied

Selected enrichment was applied.

### Apply failed

At least one selected book failed to apply.
