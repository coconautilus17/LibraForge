---
actors:
- library-owner
references:
- kind: code
  role: implementation
  target: app/static/enrichment-forge.js#renderBatchTable
- kind: code
  role: implementation
  target: app/main.py#enrichment_apply
---

# Curate a whole-library result

## Goal

Take one row of the whole-library review table into full series curation and apply it.

## Success criterion

The chosen proposal has been curated and applied to included books.
