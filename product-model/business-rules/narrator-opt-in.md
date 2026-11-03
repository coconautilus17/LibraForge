---
appliesTo:
- type: capability
  id: edit-enrichment-result
- type: capability
  id: apply-enrichment
references:
- kind: code
  role: implementation
  target: app/main.py#enrichment_apply
- kind: code
  role: implementation
  target: app/static/enrichment-forge.js#compileSeries
---

# Enrichment writes a shared narrator only by explicit choice

Found narrators are evidence and the common narrator input starts empty. Enrichment writes that narrator only after the owner opts in; blank input leaves each book’s narrator intact.
