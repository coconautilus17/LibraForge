---
availability:
- place: web
references:
- kind: code
  role: implementation
  target: app/main.py#abs_save_config
domain: audiobookshelf
---

# Save Audiobookshelf connection

Save a service address and key, then report whether verification succeeds. A failed verification does not discard the saved configuration.
