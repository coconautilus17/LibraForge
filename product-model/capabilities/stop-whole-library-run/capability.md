---
availability:
- place: web
references:
- kind: code
  role: implementation
  target: app/main.py#enrichment_batch_stop
- kind: code
  role: implementation
  target: app/enrichment_batch.py#effective_status
- kind: code
  role: implementation
  target: app/enrichment_batch.py#run_batch
domain: enrichment-forge
---

# Stop whole-library run

Request a pause between enrichment subjects while retaining compiled results.
