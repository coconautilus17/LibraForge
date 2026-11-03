---
availability:
- place: web
references:
- kind: code
  role: implementation
  target: app/enrichment_batch.py#_needs_compile
- kind: code
  role: implementation
  target: app/enrichment_batch.py#effective_status
- kind: code
  role: implementation
  target: app/main.py#enrichment_batch_start
domain: enrichment-forge
---

# Resume whole-library run

Resume a stopped or interrupted compilation, skipping complete results and revisiting pending, failed or source-degraded subjects.
