---
type: cli
actors:
- library-owner
references:
- kind: code
  role: implementation
  target: scripts/audible-metadata-fixer-v5.py#main
- kind: code
  role: implementation
  target: scripts/organize-audiobooks-by-metadata-v3_13.py#main
- kind: code
  role: implementation
  target: scripts/migrate-legacy-metadata-json.py#main
- kind: code
  role: implementation
  target: scripts/normalize-author-names.py#main
- kind: code
  role: implementation
  target: scripts/review-libraforge-report.py
---

# Command line

Maintained matching, organization and report commands plus explicit local author normalization and legacy metadata migration. Commands accept a target scope and report proposed or completed work.
