---
availability:
- place: web
- place: cli
references:
- kind: code
  role: implementation
  target: app/main.py#generate_suspect_review
- kind: code
  role: implementation
  target: scripts/review-libraforge-report.py
domain: metadata-forge
---

# Generate Suspicion Report

Apply deterministic checks to a saved match report to identify likely incorrect identities, title noise and inconsistent series groups.
