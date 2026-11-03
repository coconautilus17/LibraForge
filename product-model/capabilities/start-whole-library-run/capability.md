---
availability:
- place: web
references:
- kind: code
  role: implementation
  target: app/main.py#enrichment_batch_start
- kind: code
  role: implementation
  target: app/enrichment_batch.py#run_batch
- kind: code
  role: implementation
  target: app/static/enrichment-forge.js#startBatch
domain: enrichment-forge
---

# Start whole-library run

Compile every indexed series and standalone book sequentially into a persistent review table. Starting over replaces the saved proposal set after confirmation.
