---
availability:
- place: web
references:
- kind: code
  role: implementation
  target: app/main.py#cleanup_sidecars
- kind: code
  role: implementation
  target: app/main.py#collect_cleanup_targets
domain: danger-zone
---

# Preview sidecar cleanup

Count the matching LibraForge companion files under a selected folder, optionally including metadata files, and show size and sample paths.
