---
availability:
- place: web
- place: cli
references:
- kind: code
  role: implementation
  target: scripts/audible-metadata-fixer-v5.py#search_item
- kind: code
  role: implementation
  target: scripts/audible-metadata-fixer-v5.py#main
- kind: code
  role: implementation
  target: app/main.py#build_command
domain: metadata-forge
---

# Preview metadata matching

Match local audio against the selected provider and report proposed field changes before applying them. Supported providers are Audible's public catalog for a chosen marketplace (no login), Audible through the connected account, Audiobookshelf search and abs-agg, with an opt-in Goodreads fallback that reads Goodreads directly. A run that asks for the account while none is connected uses the public catalog instead.
