---
availability:
- place: web
references:
- kind: code
  role: implementation
  target: app/main.py#cleanup_sidecars
- kind: code
  role: implementation
  target: app/static/ui-preferences.js
domain: danger-zone
---

# Delete sidecars

Remove the selected classes of local companion metadata files and report failures. Audio files are not cleanup targets.
