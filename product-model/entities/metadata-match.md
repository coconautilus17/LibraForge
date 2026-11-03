---
domain: metadata-forge
references:
- kind: code
  role: implementation
  target: scripts/audible-metadata-fixer-v5.py#search_item
- kind: code
  role: implementation
  target: scripts/audible-metadata-fixer-v5.py#_build_report_item
- kind: code
  role: implementation
  target: app/main.py#search_audible_candidates
---

# Metadata match

A provider candidate or batch result that can be reviewed for a particular book.

## Information kept

- **Book** — Local target path and identity clues.
- **Candidate** — Proposed title, author, narrator, series, publication, identifiers, summary and cover.
- **Provider** — Source of the proposal.
- **Score** — Confidence and matching evidence.
- **Edit mode** — Full metadata, series only, or no editable match.
- **Review reasons** — Ambiguity, duration, identity or duplicate concerns.
- **Write outcome** — Planned, written, skipped, unchanged or failed fields and their destination.
