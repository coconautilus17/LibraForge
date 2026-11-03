---
appliesTo:
- type: capability
  id: compile-enrichment
- type: capability
  id: start-whole-library-run
- type: capability
  id: apply-whole-library-results
- type: capability
  id: apply-enrichment
references:
- kind: code
  role: implementation
  target: app/enrichment_batch.py#run_batch
- kind: code
  role: implementation
  target: app/enrichment_batch.py#apply_batch
- kind: code
  role: implementation
  target: app/main.py#enrichment_apply
---

# Compilation leaves library metadata unchanged until application

Single-subject and whole-library compilation create reviewable proposals. Only explicit application writes selected fields; bulk application skips already-applied rows and never writes entries with no audio.
