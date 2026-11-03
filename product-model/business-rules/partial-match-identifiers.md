---
appliesTo:
- type: capability
  id: preview-metadata
- type: capability
  id: apply-metadata
references:
- kind: code
  role: implementation
  target: app/fixer/scoring.py#metadata_from_product
- kind: code
  role: implementation
  target: scripts/audible-metadata-fixer-v5.py#should_skip_due_to_marker
---

# A partial match never gives a book another book's identifiers

A series-only match is another book of the same series, so it supplies only the grouping fields: the book keeps its own title, narrator, ASIN, ISBN and subtitle, and an ASIN an earlier series-only write left behind is dropped. A match to another recording of the same book keeps the book's own narrator, ASIN, release year and ISBN and supplies no cover. Later runs search a series-only book again, and a different-recording book that has no real ASIN of its own, instead of skipping it as already processed.
