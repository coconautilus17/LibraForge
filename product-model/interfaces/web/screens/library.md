---
entities:
- entity: audible-purchase
  shows:
  - Identity
  - Details
  - Owned
  - Duplicate action
  - Download result
  collects:
  - Duplicate action
- entity: audible-account
  shows:
  - Name
  - Marketplace
- entity: run
  shows:
  - Tool
  - Target
  - Options
  - Progress
  - Results
  - Timing
- entity: run-log
  shows:
  - Tool
  - Timing
  - Outcome
  - Output
- entity: audiobook
  shows:
  - Path
  - Title
  - Identifiers
entryPoints:
- web: /library
references:
- kind: code
  role: implementation
  target: app/main.py#library_list
---

# Library Downloader

Browse Audible purchases and download selected books.
