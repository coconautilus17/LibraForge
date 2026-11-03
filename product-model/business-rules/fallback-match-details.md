---
appliesTo:
- type: capability
  id: preview-metadata
- type: capability
  id: apply-metadata
references:
- kind: code
  role: implementation
  target: scripts/audible-metadata-fixer-v5.py#find_audiosilo_match
- kind: code
  role: implementation
  target: scripts/audible-metadata-fixer-v5.py#find_series_member_match
---

# A fallback match writes Audible's own details, and never an ASIN Audible doesn't list

A book found through its series or through AudioSilo is written from its Audible listing, looked up by its ASIN, and judged on the same evidence as an Audible search result. When Audible doesn't list the ASIN AudioSilo gives, the book is matched from AudioSilo's record and keeps its own ASIN.
