---
appliesTo:
- type: capability
  id: preview-legacy-metadata-migration
- type: capability
  id: apply-legacy-metadata-migration
- type: capability
  id: apply-enrichment
references:
- kind: code
  role: implementation
  target: app/abs_client.py#_decide_legacy_metadata_json
- kind: code
  role: implementation
  target: app/abs_client.py#reconcile_legacy_metadata_json
---

# Legacy metadata reconciliation favors the more recently edited record

For a book’s own legacy metadata file, identical content or a newer Audiobookshelf record allows removal. A newer file contributes differing nonblank values before removal. Unreadable content or an unsuccessful reconciliation is retained.
