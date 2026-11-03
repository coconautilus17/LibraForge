---
appliesTo:
- type: entity
  id: metadata-match
  facts:
  - Score
  - Edit mode
  - Review reasons
  - Write outcome
references:
- kind: code
  role: implementation
  target: scripts/audible-metadata-fixer-v5.py#search_item
- kind: code
  role: implementation
  target: scripts/audible-metadata-fixer-v5.py#main
---

# Unresolved matches remain available for review

A below-threshold score, missing title or author, no editable identity, unresolved tie, tags and runtime that point to two recordings of the same book, or duplicate identity conflict prevents the corresponding automatic match write and is represented in the review result.
