---
entities:
- entity: audiobook
  shows:
  - Path
  - Companions
entryPoints:
- web: /settings#cleanup
references:
- kind: code
  role: implementation
  target: app/main.py#cleanup_sidecars
---

# Clean up sidecars

Preview and remove local companion metadata files.
