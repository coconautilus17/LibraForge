---
appliesTo:
- type: capability
  id: preview-metadata
- type: capability
  id: apply-metadata
- type: capability
  id: cancel-run
references:
- kind: code
  role: implementation
  target: app/main.py#find_conflicting_run
- kind: code
  role: implementation
  target: app/main.py#start_run
---

# A metadata run is refused while another live run covers an overlapping folder

A new metadata run for the same path or overlapping subtree is refused while an earlier tracked run is still live, including cancelled metadata writes that are draining.
