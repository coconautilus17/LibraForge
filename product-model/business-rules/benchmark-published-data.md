---
appliesTo:
- type: capability
  id: publish-benchmark-page
- type: capability
  id: download-benchmark-books
- type: capability
  id: count-hidden-books
references:
- kind: code
  role: implementation
  target: dev/benchmark/bench_data.py#public_tags
- kind: code
  role: implementation
  target: .gitignore
---

# Only the tags a matcher reads are ever published

The dataset and every run stay out of the repository. The page, the book list and the mock files carry only the
tags a matcher reads: no comments, descriptions, cover art, copyright text, store, DRM or encoder fields. Nothing
published says where the runs were made.

## Rationale

The dataset is a personal library and the repository is public. The tags a matcher reads are facts about the book
(title, credits, series, dates, identifiers); the rest is someone's writing or says where a file came from.
