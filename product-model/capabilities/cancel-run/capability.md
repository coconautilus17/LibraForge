---
availability:
- place: web
references:
- kind: code
  role: implementation
  target: app/main.py#cancel_run
- kind: code
  role: implementation
  target: app/main.py#get_draining
- kind: code
  role: implementation
  target: scripts/audible-metadata-fixer-v5.py#main
---

# Cancel run

Request cancellation of an active metadata, conversion, local chapter-detection or organizer process. Metadata writes already in flight are allowed to finish draining.
