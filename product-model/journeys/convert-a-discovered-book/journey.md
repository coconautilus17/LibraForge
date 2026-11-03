---
actors:
- library-owner
references:
- kind: code
  role: implementation
  target: app/static/m4b-tool.js#renderDiscoveryResults
- kind: code
  role: implementation
  target: app/main.py#run_m4b_worker
---

# Convert a discovered book

## Goal

Turn a book found by M4B Tool discovery into a single M4B.

## Success criterion

The selected source has produced a merged M4B.
